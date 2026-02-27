/*==================================================================================[HWBCPSim.cc]
Copyright (c) 2026, MiniSAT-Accel

Hardware BCP simulation bridge (Python).
=================================================================================================*/

#include "minisat/utils/HWBCPSim.h"

#ifdef HW_BCP_SIM

#include <Python.h>
#include <stdio.h>
#include <string>
#include <unistd.h>

namespace Minisat {

namespace {
PyObject* module = NULL;
PyObject* fn_init = NULL;
PyObject* fn_add_clause = NULL;
PyObject* fn_disable_clause = NULL;
PyObject* fn_set_assignment = NULL;
PyObject* fn_run_bcp = NULL;
PyObject* fn_shutdown = NULL;

std::string find_repo_root() {
    const char* env = getenv("MINISAT_ACCEL_ROOT");
    if (env && *env)
        return std::string(env);

    char cwd[4096];
    if (!getcwd(cwd, sizeof(cwd)))
        return std::string(".");

    std::string base(cwd);
    const char* candidates[] = { "", "/..", "/../.." };
    for (size_t i = 0; i < (sizeof(candidates) / sizeof(candidates[0])); i++) {
        const char* suffix = candidates[i];
        std::string root = base + suffix;
        std::string probe = root + "/simulation/bcp_hw_bridge.py";
        if (access(probe.c_str(), F_OK) == 0)
            return root;
    }

    return base;
}

void ensure_python() {
    if (!Py_IsInitialized())
        Py_Initialize();

    if (module)
        return;

    std::string root = find_repo_root();
    std::string sim_path = root + "/simulation";

    PyObject* sys_path = PySys_GetObject((char*)"path"); // borrowed
    PyObject* py_path = PyUnicode_FromString(sim_path.c_str());
    PyList_Append(sys_path, py_path);
    Py_DECREF(py_path);

    module = PyImport_ImportModule("bcp_hw_bridge");
    if (!module) {
        PyErr_Print();
        fprintf(stderr, "Failed to import bcp_hw_bridge from %s\n", sim_path.c_str());
        exit(1);
    }

    fn_init = PyObject_GetAttrString(module, "init");
    fn_add_clause = PyObject_GetAttrString(module, "add_clause");
    fn_disable_clause = PyObject_GetAttrString(module, "disable_clause");
    fn_set_assignment = PyObject_GetAttrString(module, "set_assignment");
    fn_run_bcp = PyObject_GetAttrString(module, "run_bcp");
    fn_shutdown = PyObject_GetAttrString(module, "shutdown");

    if (!fn_init || !fn_add_clause || !fn_disable_clause || !fn_set_assignment || !fn_run_bcp || !fn_shutdown) {
        PyErr_Print();
        fprintf(stderr, "Failed to resolve bcp_hw_bridge API\n");
        exit(1);
    }
}

int encode_assignment(lbool val) {
    if (val == l_True) return 2;
    if (val == l_False) return 1;
    return 0;
}

} // namespace

void HWBCPSim::init(int num_vars) {
    ensure_python();
    PyObject* arg = PyLong_FromLong(num_vars);
    PyObject* result = PyObject_CallFunctionObjArgs(fn_init, arg, NULL);
    Py_DECREF(arg);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "bcp_hw_bridge.init failed\n");
        exit(1);
    }
    Py_DECREF(result);
}

void HWBCPSim::addClause(int clause_id, const vec<Lit>& lits) {
    ensure_python();
    PyObject* py_id = PyLong_FromLong(clause_id);
    PyObject* py_list = PyList_New(lits.size());
    for (int i = 0; i < lits.size(); i++) {
        PyObject* v = PyLong_FromLong(toInt(lits[i]));
        PyList_SetItem(py_list, i, v); // steals ref
    }

    PyObject* result = PyObject_CallFunctionObjArgs(fn_add_clause, py_id, py_list, NULL);
    Py_DECREF(py_id);
    Py_DECREF(py_list);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "bcp_hw_bridge.add_clause failed\n");
        exit(1);
    }
    Py_DECREF(result);
}

void HWBCPSim::disableClause(int clause_id) {
    ensure_python();
    PyObject* py_id = PyLong_FromLong(clause_id);
    PyObject* result = PyObject_CallFunctionObjArgs(fn_disable_clause, py_id, NULL);
    Py_DECREF(py_id);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "bcp_hw_bridge.disable_clause failed\n");
        exit(1);
    }
    Py_DECREF(result);
}

void HWBCPSim::setAssignment(Var v, lbool val) {
    ensure_python();
    PyObject* py_var = PyLong_FromLong(v);
    PyObject* py_val = PyLong_FromLong(encode_assignment(val));
    PyObject* result = PyObject_CallFunctionObjArgs(fn_set_assignment, py_var, py_val, NULL);
    Py_DECREF(py_var);
    Py_DECREF(py_val);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "bcp_hw_bridge.set_assignment failed\n");
        exit(1);
    }
    Py_DECREF(result);
}

void HWBCPSim::runBCP(int false_lit, vec<HWImplication>& out_impls, int& out_conflict_id) {
    ensure_python();
    out_impls.clear();
    out_conflict_id = -1;

    PyObject* py_false = PyLong_FromLong(false_lit);
    PyObject* result = PyObject_CallFunctionObjArgs(fn_run_bcp, py_false, NULL);
    Py_DECREF(py_false);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "bcp_hw_bridge.run_bcp failed\n");
        exit(1);
    }

    PyObject* py_conflict = PyDict_GetItemString(result, "conflict");
    PyObject* py_impls = PyDict_GetItemString(result, "implications");
    if (py_conflict)
        out_conflict_id = (int)PyLong_AsLong(py_conflict);

    if (py_impls && PyList_Check(py_impls)) {
        Py_ssize_t n = PyList_Size(py_impls);
        for (Py_ssize_t i = 0; i < n; i++) {
            PyObject* tup = PyList_GetItem(py_impls, i);
            if (!tup || !PyTuple_Check(tup) || PyTuple_Size(tup) != 3)
                continue;
            HWImplication impl;
            impl.var = (Var)PyLong_AsLong(PyTuple_GetItem(tup, 0));
            impl.value = PyLong_AsLong(PyTuple_GetItem(tup, 1)) != 0;
            impl.reason_id = (int)PyLong_AsLong(PyTuple_GetItem(tup, 2));
            out_impls.push(impl);
        }
    }

    Py_DECREF(result);
}

void HWBCPSim::shutdown() {
    if (!module)
        return;
    PyObject* result = PyObject_CallFunctionObjArgs(fn_shutdown, NULL);
    if (!result) {
        PyErr_Print();
        fprintf(stderr, "bcp_hw_bridge.shutdown failed\n");
        exit(1);
    }
    Py_DECREF(result);
}

} // namespace Minisat

#else

namespace Minisat {
void HWBCPSim::init(int) {}
void HWBCPSim::addClause(int, const vec<Lit>&) {}
void HWBCPSim::disableClause(int) {}
void HWBCPSim::setAssignment(Var, lbool) {}
void HWBCPSim::runBCP(int, vec<HWImplication>&, int&) {}
void HWBCPSim::shutdown() {}
}

#endif
