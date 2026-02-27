/*==================================================================================[HWBCPSim.h]
Copyright (c) 2026, MiniSAT-Accel

Hardware BCP simulation bridge (Python).
=================================================================================================*/

#ifndef Minisat_HWBCPSim_h
#define Minisat_HWBCPSim_h

#include "minisat/mtl/Vec.h"
#include "minisat/core/SolverTypes.h"

namespace Minisat {

struct HWImplication {
    Var var;
    bool value;      // true=TRUE, false=FALSE
    int reason_id;   // hardware clause id
};

class HWBCPSim {
public:
    static void init(int num_vars);
    static void addClause(int clause_id, const vec<Lit>& lits);
    static void disableClause(int clause_id);
    static void setAssignment(Var v, lbool val);
    static void runBCP(int false_lit, vec<HWImplication>& out_impls, int& out_conflict_id);
    static void shutdown();
};

}

#endif
