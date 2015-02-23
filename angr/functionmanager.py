import networkx
import claripy

class Function(object):
    '''
    A representation of a function and various information about it.
    '''
    def __init__(self, function_manager, addr, name=None):
        '''
        Function constructor

        @param addr             The address of the function
        @param name             (Optional) The name of the function
        '''
        self._transition_graph = networkx.DiGraph()
        self._ret_sites = set()
        self._call_sites = {}
        self._retn_addr_to_call_site = {}
        self._addr = addr
        self._function_manager = function_manager
        self.name = name

        if self.name is None:
            # Try to get a name from project.ld
            self.name = self._function_manager._project.ld.find_symbol_name(addr)

        # Register offsets of those arguments passed in registers
        self._argument_registers = []
        # Stack offsets of those arguments passed in stack variables
        self._argument_stack_variables = []

        # These properties are set by VariableManager
        self._bp_on_stack = False
        self._retaddr_on_stack = False

        self._sp_delta = 0

        self.cc = None

    @property
    def operations(self):
        '''
        All of the operations that are done by this functions.
        '''
        operations = [ ]
        for b in self.basic_blocks:
            if b in self._function_manager._project.ld.memory:
                try:
                    operations.extend(self._function_manager._project.block(b).operations)
                except AngrTranslationError:
                    continue
        return operations

    @property
    def code_constants(self):
        '''
        All of the constants that are used by this functions's code.
        '''
        # TODO: remove link register values
        constants = [ ]
        for b in self.basic_blocks:
            if b in self._function_manager._project.ld.memory:
                try:
                    constants.extend(v.value for v in self._function_manager._project.block(b).constants)
                except AngrTranslationError:
                    continue
        return constants

    @property
    def runtime_values(self):
        '''
        All of the concrete values used by this function at runtime (i.e., including passed-in arguments and global values).
        '''
        constants = set()
        for b in self.basic_blocks:
            for sirsb in self._function_manager._cfg.get_all_irsbs(b):
                for s in sirsb.successors + sirsb.unsat_successors:
                    for a in s.log.actions:
                        for ao in a.all_objects:
                            if not isinstance(ao.ast, claripy.A):
                                constants.add(ao.ast)
                            elif not ao.ast.symbolic:
                                constants.add(s.se.any_int(ao.ast))
        return constants

    def __str__(self):
        if self.name is None:
            s = 'Function [0x%x]\n' % (self._addr)
        else:
            s = 'Function %s [0x%x]\n' % (self.name, self._addr)
        s += 'SP difference: %d\n' % self.sp_delta
        s += 'Has return: %s\n' % self.has_return
        s += 'Arguments: reg: %s, stack: %s\n' % \
            (self._argument_registers,
             self._argument_stack_variables)
        s += 'Blocks: [%s]' % ", ".join([hex(i) for i in self._transition_graph.nodes()])
        return s

    def __repr__(self):
        if self.name is None:
            return '<Function 0x%x>' % (self._addr)
        else:
            return '<Function %s (0x%x)>' % (self.name, self._addr)

    @property
    def startpoint(self):
        return self._addr

    @property
    def endpoints(self):
        return list(self._ret_sites)

    def transit_to(self, from_addr, to_addr):
        '''
        Registers an edge between basic blocks in this function's transition graph

        @param from_addr            The address of the basic block that control
                                    flow leaves during this transition
        @param to_addr              The address of the basic block that control
                                    flow enters during this transition
        '''
        self._transition_graph.add_edge(from_addr, to_addr, type='transition')

    def return_from_call(self, first_block_addr, to_addr):
        self._transition_graph.add_edge(first_block_addr, to_addr, type='return_from_call')

    def add_block(self, addr):
        '''
        Registers a basic block as part of this function

        @param addr                 The address of the basic block to add
        '''
        self._transition_graph.add_node(addr)

    def add_return_site(self, return_site_addr):
        '''
        Registers a basic block as a site for control flow to return from this function

        @param return_site_addr     The address of the basic block ending with a return
        '''
        self._ret_sites.add(return_site_addr)

    def add_call_site(self, call_site_addr, call_target_addr, retn_addr):
        '''
        Registers a basic block as calling a function and returning somewhere

        @param call_site_addr       The basic block that ends in a call
        @param call_target_addr     The target of said call
        @param retn_addr            The address that said call will return to
        '''
        self._call_sites[call_site_addr] = (call_target_addr, retn_addr)
        self._retn_addr_to_call_site[retn_addr] = call_site_addr

    def get_call_sites(self):
        '''
        Gets a list of all the basic blocks that end in calls

        @returns                    What the hell do you think?
        '''
        return self._call_sites.keys()

    def get_call_target(self, callsite_addr):
        '''
        Get the target of a call

        @param callsite_addr        The address of the basic block that ends in
                                    a call

        @returns                    The target of said call
        '''
        if callsite_addr in self._call_sites:
            return self._call_sites[callsite_addr][0]
        return None

    def get_call_return(self, callsite_addr):
        '''
        Get the hypothetical return address of a call

        @param callsite_addr        The address of the basic block that ends in
                                    a call

        @returns                    The likely return target of said call
        '''
        if callsite_addr in self._call_sites:
            return self._call_sites[callsite_addr][1]
        return None

    @property
    def basic_blocks(self):
        return self._transition_graph.nodes()

    @property
    def transition_graph(self):
        return self._transition_graph

    def dbg_print(self):
        '''
        Returns a representation of the list of basic blocks in this function
        '''
        return "[%s]" % (', '.join(('0x%08x' % n) for n in self._transition_graph.nodes()))

    def dbg_draw(self, filename):
        '''
        Draw the graph and save it to a PNG file
        '''
        import matplotlib.pyplot as pyplot
        tmp_graph = networkx.DiGraph()
        for edge in self._transition_graph.edges():
            node_a = "0x%08x" % edge[0]
            node_b = "0x%08x" % edge[1]
            if node_b in self._ret_sites:
                node_b += "[Ret]"
            if node_a in self._call_sites:
                node_a += "[Call]"
            tmp_graph.add_edge(node_a, node_b)
        pos = networkx.graphviz_layout(tmp_graph, prog='fdp')
        networkx.draw(tmp_graph, pos, node_size=1200)
        pyplot.savefig(filename)

    def add_argument_register(self, reg_offset):
        '''
        Registers a register offset as being used as an argument to the function

        @param reg_offset           The offset of the register to register
        '''
        if reg_offset in self._function_manager.arg_registers and \
                    reg_offset not in self._argument_registers:
            self._argument_registers.append(reg_offset)

    def add_argument_stack_variable(self, stack_var_offset):
        if stack_var_offset not in self._argument_stack_variables:
            self._argument_stack_variables.append(stack_var_offset)

    @property
    def arguments(self):
        if self.cc is None:
            return self._argument_registers, self._argument_stack_variables
        else:
            return self.cc.arguments

    @property
    def bp_on_stack(self):
        return self._bp_on_stack

    @bp_on_stack.setter
    def bp_on_stack(self, value):
        self._bp_on_stack = value

    @property
    def retaddr_on_stack(self):
        return self._retaddr_on_stack

    @retaddr_on_stack.setter
    def retaddr_on_stack(self, value):
        self._retaddr_on_stack = value

    @property
    def sp_delta(self):
        return self._sp_delta

    @sp_delta.setter
    def sp_delta(self, value):
        self._sp_delta = value

    @property
    def has_return(self):
        return len(self._ret_sites) > 0

class FunctionManager(object):
    '''
    This is a function boundaries management tool. It takes in intermediate
    results during CFG generation, and manages a function map of the binary.
    '''
    def __init__(self, project, cfg):
        self._project = project
        self._cfg = cfg
        # A map that uses function starting address as the key, and maps
        # to a function class
        self._function_map = {}
        self.interfunction_graph = networkx.DiGraph()

        # Registers used for passing arguments around
        self.arg_registers = project.arch.argument_registers

    def _create_function_if_not_exist(self, function_addr):
        if function_addr not in self._function_map:
            self._function_map[function_addr] = Function(self, function_addr)
            self._function_map[function_addr].add_block(function_addr)

    def call_to(self, function_addr, from_addr, to_addr, retn_addr):
        self._create_function_if_not_exist(function_addr)
        self._create_function_if_not_exist(to_addr)
        self._function_map[function_addr].add_call_site(from_addr, to_addr, retn_addr)
        self.interfunction_graph.add_edge(function_addr, to_addr)

    def return_from(self, function_addr, from_addr, to_addr=None): #pylint:disable=unused-argument
        self._create_function_if_not_exist(function_addr)
        self._function_map[function_addr].add_return_site(from_addr)

    def transit_to(self, function_addr, from_addr, to_addr):
        self._create_function_if_not_exist(function_addr)
        self._function_map[function_addr].transit_to(from_addr, to_addr)

    def return_from_call(self, function_addr, first_block_addr, to_addr):
        self._create_function_if_not_exist(function_addr)
        self._function_map[function_addr].return_from_call(first_block_addr, to_addr)

    @property
    def functions(self):
        return self._function_map

    def function(self, addr=None, name=None):
        if addr and addr in self._function_map:
            return self._function_map[addr]
        elif name:
            funcs = [ i for i in self._function_map.values() if i.name == name ]
            if funcs:
                return funcs[0]
            else:
                return None
        else:
            return None

    def dbg_print(self):
        result = ''
        for func_addr, func in self._function_map.items():
            f_str = "Function 0x%08x\n%s\n" % (func_addr, func.dbg_print())
            result += f_str
        return result

    def dbg_draw(self):
        for func_addr, func in self._function_map.items():
            filename = "dbg_function_0x%08x.png" % func_addr
            func.dbg_draw(filename)

from .errors import AngrTranslationError
