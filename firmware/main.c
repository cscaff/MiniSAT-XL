/*
 * MiniSAT-XL SoC firmware -- minimal CDCL solver using BCP accelerator.
 *
 * Runs a tiny 3-variable, 3-clause CNF instance and writes SAT/UNSAT result
 * to a known MMIO register for the testbench to verify.
 *
 * Tiny instance (0-indexed variables, literal encoding: 2*var+polarity):
 *   Clause 0: (x0 ∨ x1)   lits [0, 2]
 *   Clause 1: (¬x0 ∨ x2)  lits [1, 4]
 *   Clause 2: (¬x1 ∨ ¬x2) lits [3, 5]
 *
 * Expected result: SAT  (e.g. x0=T, x1=F, x2=T)
 *
 * MMIO map (base addresses defined in soc/soc.py):
 *   CSR_BASE = 0x40000000
 *     +0x00  control  (W)  bit0=start, bit1=conflict_ack
 *     +0x04  false_lit(W)
 *     +0x08  status   (R)  bit0=busy, bit1=done, bit2=conflict
 *     +0x0C  cc_id    (R)  conflict_clause_id
 *     +0x10  impl     (R)  pop-on-read: [12:0]=var,[13]=value,[26:14]=reason,[31]=valid
 *     +0x14  result   (W)  1=SAT, 2=UNSAT
 *
 *   CLAUSE_BASE  = 0x10000000  (4 words/clause; word3 write triggers wr_en)
 *   ASSIGN_BASE  = 0x20000000  (1 word/var; [1:0]=value)
 *   OCC_LEN_BASE = 0x30000000  (1 word/lit; [6:0]=length)
 *   OCC_CID_BASE = 0x30010000  (flat; word = lit*100 + idx)
 */

#include <stdint.h>

/* ---- MMIO helpers ---- */
#define MMIO_W(addr, val)  (*(volatile uint32_t*)(addr) = (val))
#define MMIO_R(addr)       (*(volatile uint32_t*)(addr))

/* ---- Memory-map constants ---- */
#define CSR_BASE      0x40000000U
#define CSR_CONTROL   (CSR_BASE + 0x00)
#define CSR_FALSE_LIT (CSR_BASE + 0x04)
#define CSR_STATUS    (CSR_BASE + 0x08)
#define CSR_CC_ID     (CSR_BASE + 0x0C)
#define CSR_IMPL      (CSR_BASE + 0x10)
#define CSR_RESULT    (CSR_BASE + 0x14)

#define CLAUSE_BASE   0x10000000U   /* 16 bytes/clause */
#define ASSIGN_BASE   0x20000000U   /* 4 bytes/var */
#define OCC_LEN_BASE  0x30000000U   /* 4 bytes/lit */
#define OCC_CID_BASE  0x30010000U   /* 4 bytes/entry, flat */

#define MAX_WATCH_LEN 100

/* ---- Assignment values ---- */
#define UNASSIGNED  0
#define VAL_FALSE   1
#define VAL_TRUE    2
#define RESULT_SAT  1
#define RESULT_UNSAT 2

/* ---- Literal helpers ---- */
static inline uint32_t pos_lit(uint32_t var) { return 2 * var; }
static inline uint32_t neg_lit(uint32_t var) { return 2 * var + 1; }
static inline uint32_t lit_var(uint32_t lit) { return lit >> 1; }
static inline uint32_t lit_pol(uint32_t lit) { return lit & 1; }

/* ---- Hardware write helpers ---- */

static void write_clause(uint32_t cid, uint32_t sat, uint32_t size,
                          uint32_t l0, uint32_t l1, uint32_t l2,
                          uint32_t l3, uint32_t l4)
{
    volatile uint32_t *base = (volatile uint32_t *)(CLAUSE_BASE + cid * 16);
    base[0] = (sat << 16) | ((size & 7) << 17) | (l0 & 0xFFFF);
    base[1] = ((l2 & 0xFFFF) << 16) | (l1 & 0xFFFF);
    base[2] = ((l4 & 0xFFFF) << 16) | (l3 & 0xFFFF);
    base[3] = 0; /* trigger commit */
}

static void write_occurrence_list(uint32_t lit, uint32_t *cids, uint32_t len)
{
    /* length register */
    MMIO_W(OCC_LEN_BASE + lit * 4, len);
    /* clause-id entries */
    for (uint32_t i = 0; i < len; i++) {
        uint32_t flat = lit * MAX_WATCH_LEN + i;
        MMIO_W(OCC_CID_BASE + flat * 4, cids[i]);
    }
}

static void write_assignment(uint32_t var, uint32_t val)
{
    MMIO_W(ASSIGN_BASE + var * 4, val);
}

/* Run BCP: write false_lit and pulse start, then busy-wait done.
 * Returns 1 if conflict, 0 otherwise. */
static int run_bcp(uint32_t false_lit)
{
    MMIO_W(CSR_FALSE_LIT, false_lit);
    MMIO_W(CSR_CONTROL, 1); /* start */

    /* Busy-wait */
    while (!(MMIO_R(CSR_STATUS) & 0x2))
        ;

    return (MMIO_R(CSR_STATUS) >> 2) & 1;
}

static uint32_t pop_implication(uint32_t *var_out, uint32_t *val_out,
                                 uint32_t *reason_out)
{
    uint32_t w = MMIO_R(CSR_IMPL);
    if (!(w >> 31))
        return 0;
    *var_out    = w & 0x1FFF;
    *val_out    = (w >> 13) & 1;
    *reason_out = (w >> 14) & 0x1FFF;
    return 1;
}

static void ack_conflict(void)
{
    MMIO_W(CSR_CONTROL, 2); /* conflict_ack */
}

/* ---- CDCL state ---- */
#define NUM_VARS  3
static uint32_t assignment[NUM_VARS];  /* UNASSIGNED/VAL_FALSE/VAL_TRUE */
static int      trail[64];             /* decision literals (signed) */
static int      trail_len;

/* Drain FIFO and apply implications to assignment array.
 * Returns conflict clause_id, or -1 if no conflict. */
static int drain_and_apply(void)
{
    uint32_t var, val, reason;
    while (pop_implication(&var, &val, &reason)) {
        /* HW writeback already updated assignment memory; mirror locally */
        assignment[var] = val ? VAL_TRUE : VAL_FALSE;
    }
    return -1; /* no conflict in drain itself */
}

/* Pick first unassigned variable; return var_id or -1 */
static int pick_unassigned(void)
{
    for (int v = 0; v < NUM_VARS; v++)
        if (assignment[v] == UNASSIGNED)
            return v;
    return -1; /* all assigned */
}

/* --- Main firmware entry point --- */
int main(void)
{
    /* ------------------------------------------------------------------ */
    /* 1. Initialise memories                                              */
    /* ------------------------------------------------------------------ */

    /* Clause 0: (x0 ∨ x1)   */
    write_clause(0, 0, 2, pos_lit(0), pos_lit(1), 0, 0, 0);
    /* Clause 1: (¬x0 ∨ x2)  */
    write_clause(1, 0, 2, neg_lit(0), pos_lit(2), 0, 0, 0);
    /* Clause 2: (¬x1 ∨ ¬x2) */
    write_clause(2, 0, 2, neg_lit(1), neg_lit(2), 0, 0, 0);

    /* Occurrence lists (which clauses contain each literal) */
    uint32_t occ0[] = {0};          /* x0  in clause 0 */
    uint32_t occ1[] = {1};          /* ¬x0 in clause 1 */
    uint32_t occ2[] = {0};          /* x1  in clause 0 */
    uint32_t occ3[] = {2};          /* ¬x1 in clause 2 */
    uint32_t occ4[] = {1};          /* x2  in clause 1 */
    uint32_t occ5[] = {2};          /* ¬x2 in clause 2 */
    write_occurrence_list(0, occ0, 1);
    write_occurrence_list(1, occ1, 1);
    write_occurrence_list(2, occ2, 1);
    write_occurrence_list(3, occ3, 1);
    write_occurrence_list(4, occ4, 1);
    write_occurrence_list(5, occ5, 1);

    /* Initialise assignment array */
    for (int v = 0; v < NUM_VARS; v++)
        assignment[v] = UNASSIGNED;
    trail_len = 0;

    /* ------------------------------------------------------------------ */
    /* 2. CDCL loop                                                         */
    /* ------------------------------------------------------------------ */
    for (;;) {
        int var = pick_unassigned();
        if (var < 0) {
            /* All variables assigned → SAT */
            MMIO_W(CSR_RESULT, RESULT_SAT);
            return 0;
        }

        /* Decide: assign var = TRUE */
        uint32_t decided_val  = VAL_TRUE;
        assignment[var] = decided_val;
        write_assignment(var, decided_val);
        trail[trail_len++] = var; /* positive = decided */

        /* BCP propagation queue (false lits to process) */
        uint32_t queue[64];
        int      q_head = 0, q_tail = 0;

        /* The decided literal's opposite became "false": */
        /* x=TRUE → neg_lit becomes false; x=FALSE → pos_lit becomes false */
        queue[q_tail++] = (decided_val == VAL_TRUE) ? neg_lit(var) : pos_lit(var);

        int conflict_seen = 0;
        uint32_t conflict_cid = 0;

        while (q_head < q_tail && !conflict_seen) {
            uint32_t fl = queue[q_head++];
            int had_conflict = run_bcp(fl);

            if (had_conflict) {
                conflict_cid  = MMIO_R(CSR_CC_ID);
                ack_conflict();
                conflict_seen = 1;
                break;
            }

            /* Drain implications; each new assignment may add false lits */
            uint32_t ivar, ival, ireason;
            while (pop_implication(&ivar, &ival, &ireason)) {
                if (ivar < NUM_VARS) {
                    /* Mirror locally (HW writeback already updated hw mem) */
                    assignment[ivar] = ival ? VAL_TRUE : VAL_FALSE;
                    /* Queue BCP for the new false literal */
                    uint32_t new_fl = (ival) ? neg_lit(ivar) : pos_lit(ivar);
                    if (q_tail < 64)
                        queue[q_tail++] = new_fl;
                }
            }
        }

        if (conflict_seen) {
            /* Chronological backtrack: undo decision */
            if (trail_len == 0) {
                /* No more decisions to undo → UNSAT */
                MMIO_W(CSR_RESULT, RESULT_UNSAT);
                return 0;
            }
            trail_len--;
            int bvar = trail[trail_len];
            /* trail[] stores var_id (>=0) for decided-TRUE and -(var_id+1)
             * for flipped decisions.  Recover the actual var_id: */
            if (bvar < 0)
                bvar = (-bvar) - 1;
            /* Unassign var and try opposite */
            assignment[bvar] = UNASSIGNED;
            write_assignment(bvar, UNASSIGNED);

            /* Try the opposite value */
            uint32_t try_val = VAL_FALSE;
            assignment[bvar] = try_val;
            write_assignment(bvar, try_val);
            trail[trail_len++] = -(bvar + 1); /* negative = flipped */

            /* BCP for the flipped literal */
            uint32_t fl2 = (try_val == VAL_TRUE) ? neg_lit(bvar) : pos_lit(bvar);
            run_bcp(fl2);
            if (MMIO_R(CSR_STATUS) & 0x4) {
                ack_conflict();
                /* Double conflict → UNSAT for this tiny instance */
                MMIO_W(CSR_RESULT, RESULT_UNSAT);
                return 0;
            }
            /* Drain */
            uint32_t iv2, iv2val, iv2r;
            while (pop_implication(&iv2, &iv2val, &iv2r))
                if (iv2 < NUM_VARS)
                    assignment[iv2] = iv2val ? VAL_TRUE : VAL_FALSE;
        }
    }
}
