from rbbm_src.muse.Semantics.abs_sem import *
from z3 import parse_smt2_string, Optimize, Int, sat, BoolRef
import random
import string
import re


class IndependentSemantics(AbsSemantics):
    """This class implements independent semantics. This is the semantics of considering
    all possible assignments leading to delta tuples and finding the smallest set of
    tuples whose deletion will not enable any of the rules to be satisfied"""

    def __init__(self, db_conn, rules, tbl_names):
        super(IndependentSemantics, self).__init__(db_conn, rules, tbl_names)

        self.provenance = {}  # dict in the form {delta tuple: [assign1, assign2, ...]}
        self.prov_notations = {}  # dict in the form {notation: tuple}

    def find_mss(self, schema, suffix = ""):
        """implementation of approximation algorithm for independent semantics.
        Store the provenance of all possible delta tuples as a CNF and find the
        smallest satisfying assignment using a SAT solver"""

        if not self.rules:   # verify more than 0 rules
            return set()

        # delete database
        self.db.delete_tables(self.delta_tuples.keys())
        # self.db.load_database_tables(self.delta_tuples.keys(), is_delta=True)

        # convert the rules so they will store the provenance
        prov_rules, prov_tbls, proj = self.gen_prov_rules()
        print(f'prov_rules: {prov_rules}')
        print(f'prov_tbls: {prov_tbls}')
        print(f'proj: {proj}')
        # reload database with all possible and impossible relevant delta tuples
        relevant_tables = list(set([item for sublist in prov_tbls for item in sublist if "delta" not in item]))
        relevant_tables = list(set([name.split(" as")[0] + suffix for name in relevant_tables]))
        print(f'relevant_tables:{relevant_tables}')
        self.db.load_database_tables(relevant_tables, is_delta=True)

        print("solving the program")
        # evaluate the program
        assignments = self.eval(schema, prov_rules, prov_tbls, proj)
        # print(f"assignments : {assignments}")
        # process provenance into a formula
        print("process provenance...")
        self.process_provenance(assignments)
        print("convert_to_bool_formula..")
        bf = self.convert_to_bool_formula()
        print("solving the bf")
        # print(f"bf: {bf}")
        # find minimum satisfying assignment
        sol, size = self.solve_boolean_formula_with_z3_smt2(bf)
        print("solved the z3")

        # process solution to mss
        mss = self.convert_sat_sol_to_mss(sol)
        return mss

    def eval(self, schema, prov_rules, prov_tbls, proj):
        """Use end semantics to derive all possible and impossible delta tuples and store the provenance"""
        assignments = set()   # var to store the assignments

        changed = True
        derived_tuples = set()
        prev_len = 0
        while changed:
            for i in range(len(self.rules)):
                print(f"excecuting query {prov_rules[i][1]}")
                cur_rows = self.db.execute_query(prov_rules[i][1])
                print(f"done execute_query query {prov_rules[i][1]}");
                # print(f"cur_rows: {cur_rows}")
                # print(f"prov_tbls[i]: {prov_tbls[i]}")
                # print(f"proj: {proj}")
                # print(f"prov_rules[i]: {prov_rules[i]}")

                cur_assignments = self.rows_to_prov(cur_rows, prov_tbls[i], schema, proj, prov_rules[i])
                # print(f"cur_assignments: {cur_assignments}")

                # optimization: check if any new assignments before iterating over them
                # if all(assign in assignments for assign in cur_assignments):
                #     continue

                for assignment in cur_assignments:
                    if assignment not in assignments:
                        assignments.add(assignment)
                        # derived_tuples.add(assignment[0])
            # print(f"prev_len:{prev_len}, derived_tuples:{len(derived_tuples)}")
            if prev_len == len(derived_tuples):
                changed = False
            prev_len = len(derived_tuples)
        print(f"return assignments: len assignment = {len(assignments)}")
        return [list(x) for x in assignments]

    def gen_prov_rules(self):
        """convert every rule to a rule that outputs the provenance"""
        prov_rules = []
        prov_tbls = []
        proj = []
        for i in range(len(self.rules)):
            query = self.rules[i]
            q_parts = query[1].lower().split("from")
            proj = q_parts[0].split('select')[1].strip().split(',')
            proj = [e.strip() for e in proj]
            rest = q_parts[1].split("where")
            prov_tbls.append([tbl.strip() for tbl in rest[0].strip().split(',')])
            # prov_tbls.append([tbl.strip().split(" as ")[1] for tbl in rest[0].strip().split(',')])
            prov_proj = ""
            prov_lst = []
            for tbl in prov_tbls[i]:
                if "as" in tbl:
                    prov_proj += tbl.split("as")[1] + ".*, "
                    prov_lst.append(tbl.split("as")[0][:-1].strip())
                else:
                    prov_proj += tbl + ".*, "
            prov_proj = prov_proj[:-2]
            if len(rest) > 1:
                q_prov = "SELECT " + prov_proj + " FROM" + rest[0] + "WHERE" + rest[1]
            else:
                q_prov = "SELECT " + prov_proj + " FROM" + rest[0] + ";"
            prov_rules.append((query[0], q_prov))
        return prov_rules, prov_tbls, proj

    def handle_assignment(self, row, assignment_tuples, schema, prov_tbls, rule):
        """convert a row from the result set into an assignment of tuples"""
        s = 0
        str_row = [str(e) for e in row]
        ans = ("", "")
        for tbl in prov_tbls:
            if " as " in tbl:
                tbl = tbl.split(" as ")[0]
            e = len(schema[tbl]) + s if 'delta_' not in tbl else len(schema[tbl[6:]]) + s
            # attrs = ",".join(["'" + t + "'" if "\r" not in t else "'" + t[:-4] + "'" for t in str_row[s:e]])
            attrs = ",".join([t if "\r" not in t else t[:-4] for t in str_row[s:e]])
            txt_tbl = (tbl, "(" + attrs + ")")
            assignment_tuples.append(txt_tbl)
            if rule[0] == txt_tbl[0]:
                ans = ("delta_" + txt_tbl[0], txt_tbl[1])
            s = e
        return assignment_tuples, ans

    def rows_to_prov(self, res, prov_tbls, schema, proj, rule):
        # cur_rows, prov_tbls[i], schema, proj, prov_rules[i]
        """separate every result row into provenance tuples"""
        proj_attrs = []
        for p in proj:
            t = tuple(p.split("."))
            proj_attrs.append(t)
        assignments = []
        for i in range(len(res)):
            example_tuples = []
            row = res[i]
            example_tuples, ans = self.handle_assignment(row, example_tuples, schema, prov_tbls, rule)
            example_tuples = [ans] + example_tuples
            assignments.append(frozenset(example_tuples))
        return assignments

    def process_provenance(self, assignments):
        """get the provenance of each tuple"""
        for assign in assignments:
            if assign[0] not in self.provenance:
                self.provenance[assign[0]] = []
            self.provenance[assign[0]].append(assign[1:])  # add assignment to the prov of this tuple

    # def convert_to_bool_formula(self):
    #     """build the boolean formula based on the provenance"""
    #     def random_string(string_length=10):
    #         # Generate a random string of fixed length
    #         letters = string.ascii_lowercase
    #         return ''.join(random.choice(letters) for i in range(string_length))
    #
    #     bf = "(or "  # the boolean formula that will be evaluated
    #     for delta_tup in self.provenance:
    #         assignments = self.provenance[delta_tup]
    #         if len(assignments) > 1:
    #             bf += "(or "
    #         for assign in assignments:
    #             bf += "(and " if len(assign) > 1 else ""
    #             for tup in assign:
    #                 if tup not in self.prov_notations:
    #                     if "delta_" in tup[0] and (tup[0][6:], tup[1]) in self.prov_notations:  # tup is a delta tuple and its regular counterpart has an annotation
    #                         self.prov_notations[tup] = "(not " + self.prov_notations[(tup[0][6:], tup[1])] + ")"
    #                     elif ("delta_" + tup[0], tup[1]) in self.prov_notations:  # symmetric case
    #                         self.prov_notations[tup] = self.prov_notations[("delta_" + tup[0], tup[1])][5:-1]
    #                     else:
    #                         annotation = random_string()
    #                         annotation = "(not " + annotation + ")" if "delta_" in tup[0] else annotation
    #                         self.prov_notations[tup] = annotation
    #                 bf += self.prov_notations[tup] + " "
    #             bf = bf[:-1] + ") " if len(assign) > 1 else bf[:-1] + " "
    #         if len(assignments) > 1:
    #             bf = bf[:-1] + ") "
    #
    #     return "(not " + bf[:-1] + ")) "

    def convert_to_bool_formula(self):
        """build the boolean formula based on the provenance"""
        def random_string(string_length=10):
            # Generate a random string of fixed length
            letters = string.ascii_lowercase
            return ''.join(random.choice(letters) for i in range(string_length))

        bf = "(or "  # the boolean formula that will be evaluated
        print(f"len(provenance): {len(self.provenance)}")
        # lp = list(self.provenance)
        # print(lp[:10])
        # print(f"self.provenance[lp[0]]: {self.provenance[lp[0]]}")
        i=0
        for delta_tup in self.provenance:
            if(i%1000==0):
                print(f"assignments for :{i}")
            assignments = self.provenance[delta_tup]
            if len(assignments) > 1:
                bf += "(or "
            for assign in assignments:
                bf += "(and " if len(assign) > 1 else ""
                for tup in assign:
                    if tup not in self.prov_notations:
                        if "delta_" in tup[0] and (tup[0][6:], tup[1]) in self.prov_notations:  # tup is a delta tuple and its regular counterpart has an annotation
                            self.prov_notations[tup] = self.prov_notations[(tup[0][6:], tup[1])][5:-1]
                        elif ("delta_" + tup[0], tup[1]) in self.prov_notations:  # symmetric case
                            self.prov_notations[tup] = "(not " + self.prov_notations[("delta_" + tup[0], tup[1])] + ")"
                        else:
                            annotation = random_string()
                            annotation = "(not " + annotation + ")" if not "delta_" in tup[0] else annotation
                            self.prov_notations[tup] = annotation
                    bf += self.prov_notations[tup] + " "
                bf = bf[:-1] + ") " if len(assign) > 1 else bf[:-1] + " "
            if len(assignments) > 1:
                bf = bf[:-1] + ") "
            i+=1
        # print(f"self.prov_notations: {self.prov_notations}")
        return "(not " + bf[:-1] + ")) "

    # def solve_boolean_formula_with_z3_smt2(self, bf):
    #     """Find minimum satisfying assignemnt for the boolean formula.
    #     # Example:
    #     # >>> bf = '(and (or a b) (not (and a c)))'
    #     # >>> appeared_symbol_list = ['a', 'b', 'c']
    #     # >>> solve_boolean_formula_with_z3_smt2(bf, appeared_symbol_list)
    #     # ([b = True, a = False, c = False, s = 1], 1)
    #     """
    #     # print(bf)
    #     appeared_symbol_list = list(set([a if "not " not in a else a[5:-1] for a in self.prov_notations.values()]))
    #     declaration_str = '\n'.join(list(map(lambda x: '(declare-const {} Bool)'.format(x), appeared_symbol_list)))
    #     declaration_str += '\n(declare-const s Int)'
    #     declaration_str += '\n(define-fun b2i ((x Bool)) Int (ite x 1 0))'
    #
    #     size_str = '(+ {})'.format(' '.join(list(map(lambda x: '(b2i {})'.format(x), appeared_symbol_list))))
    #     assert_str = '(assert {})\n'.format(bf)
    #     assert_str += '(assert (= s {}))\n(assert (>= s 0))'.format(size_str)  # changed from (> s 0)
    #
    #     z3_bf = parse_smt2_string(declaration_str + '\n' + assert_str)
    #     opt = Optimize()
    #     opt.add(z3_bf)
    #     s = Int('s')
    #     opt.maximize(s)  # changed from opt.minimize(s)
    #
    #     if opt.check() == sat:
    #         best_model = opt.model()
    #         min_size = 0
    #         for cl in best_model:
    #             if isinstance(best_model[cl], BoolRef) and best_model[cl]:
    #                 min_size += 1
    #         return best_model, min_size
    #     else:
    #         return None, -1

    def solve_boolean_formula_with_z3_smt2(self, bf):
        """Find minimum satisfying assignemnt for the boolean formula.
        # Example:
        # >>> bf = '(and (or a b) (not (and a c)))'
        # >>> appeared_symbol_list = ['a', 'b', 'c']
        # >>> solve_boolean_formula_with_z3_smt2(bf, appeared_symbol_list)
        # ([b = True, a = False, c = False, s = 1], 1)
        """
        appeared_symbol_list = list(set([a if "not " not in a else a[5:-1] for a in self.prov_notations.values()]))
        declaration_str = '\n'.join(list(map(lambda x: '(declare-const {} Bool)'.format(x), appeared_symbol_list)))
        declaration_str += '\n(declare-const s Int)'
        declaration_str += '\n(define-fun b2i ((x Bool)) Int (ite x 1 0))'

        size_str = '(+ {})'.format(' '.join(list(map(lambda x: '(b2i {})'.format(x), appeared_symbol_list))))
        assert_str = '(assert {})\n'.format(bf)
        assert_str += '(assert (= s {}))\n(assert (>= s 0))'.format(size_str)  # changed from (> s 0)

        z3_bf = parse_smt2_string(declaration_str + '\n' + assert_str)
        opt = Optimize()
        opt.add(z3_bf)
        s = Int('s')
        opt.minimize(s)  # changed from opt.minimize(s)

        if opt.check() == sat:
            best_model = opt.model()
            min_size = 0
            for cl in best_model:
                if isinstance(best_model[cl], BoolRef) and best_model[cl]:
                    min_size += 1
            return best_model, min_size
        else:
            return None, -1

    # def convert_sat_sol_to_mss(self, sol):
    #     """include in mss all literals in solution that get the value False"""
    #     notations_mss = set()
    #     s = sol.sexpr().replace("\n", "").replace("()", "")
    #     literals = re.findall('\(([^)]+)', s)
    #     for literal_val in literals:
    #         if "Int" not in literal_val:
    #             mid_exp = literal_val.replace("define-fun ", "").replace(" Bool", "")
    #             literal, val = mid_exp.split("  ")
    #             if val == " false":
    #                 notations_mss.add(literal)
    #     mss = set([t for t in self.prov_notations if self.prov_notations[t] in notations_mss])
    #     return mss

    def convert_sat_sol_to_mss(self, sol):
        """include in mss all literals in solution that get the value False"""
        notations_mss = set()
        s = sol.sexpr().replace("\n", "").replace("()", "")
        literals = re.findall('\(([^)]+)', s)
        for literal_val in literals:
            if "Int" not in literal_val:
                mid_exp = literal_val.replace("define-fun ", "").replace(" Bool", "")
                literal, val = mid_exp.split("  ")
                if val == " true":
                    notations_mss.add("(not " + literal + ")")
        mss = set([t for t in self.prov_notations if self.prov_notations[t] in notations_mss])
        return mss