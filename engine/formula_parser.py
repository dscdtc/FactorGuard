"""
受限公式解析器 - 使用 Lark 库实现因子公式的安全解析。

功能：
- 基于上下文无关文法的公式解析
- 字段/函数白名单校验
- 窗口参数合法性检查
- 除零/对数负数等风险检测
"""

from lark import Lark, Transformer
from dataclasses import dataclass, field
from typing import Optional, Any, Union

# ============================================================
# 文法定义
# ============================================================

GRAMMAR = r"""
    start: expression
    
    ?expression: add_expr
    
    ?add_expr: mul_expr
        | add_expr "+" mul_expr   -> add
        | add_expr "-" mul_expr   -> sub
    
    ?mul_expr: unary
        | mul_expr "*" unary      -> mul
        | mul_expr "/" unary      -> div
    
    ?unary: atom
        | "-" unary               -> neg
    
    ?atom: NUMBER
        | CNAME
        | func_call
        | "(" expression ")"
    
    func_call: CNAME "(" [expression ("," expression)*] ")"
    
    NUMBER: /-?\d+(\.\d+)?/
    CNAME: /[a-zA-Z_][a-zA-Z0-9_]*/
    %ignore " "
"""

# ============================================================
# 白名单
# ============================================================

FIELD_WHITELIST = {
    'open', 'high', 'low', 'close', 'volume', 'amount',
    'total_mv', 'circ_mv', 'turnover_rate', 'pe_ttm',
}

FUNCTION_WHITELIST = {
    'delay', 'ts_mean', 'ts_sum', 'ts_std', 'ts_min', 'ts_max',
    'rank_cs', 'zscore_cs', 'log', 'abs', 'sign', 'sqrt',
}

# 带窗口参数的函数（第二个参数为窗口大小）
WINDOW_FUNCTIONS = {'delay', 'ts_mean', 'ts_sum', 'ts_std', 'ts_min', 'ts_max'}

# 可能为零的字段（用于除零风险检测）
ZERO_RISK_FIELDS = {'volume', 'amount', 'turnover_rate'}


# ============================================================
# AST 节点定义
# ============================================================

class ASTNode:
    """AST 节点基类"""
    pass


@dataclass
class BinOpNode(ASTNode):
    """二元运算节点"""
    op: str         # '+', '-', '*', '/'
    left: ASTNode
    right: ASTNode


@dataclass
class UnaryOpNode(ASTNode):
    """一元运算节点"""
    op: str         # '-' (neg)
    operand: ASTNode


@dataclass
class NumberNode(ASTNode):
    """数字字面量节点"""
    value: float


@dataclass
class FieldNode(ASTNode):
    """字段引用节点"""
    name: str


@dataclass
class FuncCallNode(ASTNode):
    """函数调用节点"""
    name: str
    args: list  # list[ASTNode]


# ============================================================
# Lark Transformer
# ============================================================

class FormulaTransformer(Transformer):
    """将 Lark 解析树转换为自定义 AST"""

    def start(self, items):
        return items[0]

    def add(self, items):
        return BinOpNode('+', items[0], items[1])

    def sub(self, items):
        return BinOpNode('-', items[0], items[1])

    def mul(self, items):
        return BinOpNode('*', items[0], items[1])

    def div(self, items):
        return BinOpNode('/', items[0], items[1])

    def neg(self, items):
        return UnaryOpNode('-', items[0])

    def NUMBER(self, token):
        return NumberNode(float(token.value))

    def CNAME(self, token):
        return FieldNode(token.value)

    def func_call(self, items):
        # items[0] 是 CNAME 转换后的 FieldNode，提取其 name 作为函数名
        name = items[0].name
        args = items[1:]
        return FuncCallNode(name, args)


# ============================================================
# AST 遍历辅助函数
# ============================================================

def _get_max_window(node: ASTNode) -> int:
    """递归计算 AST 的最大回看窗口"""
    if isinstance(node, NumberNode):
        return 0
    elif isinstance(node, FieldNode):
        return 0
    elif isinstance(node, UnaryOpNode):
        return _get_max_window(node.operand)
    elif isinstance(node, BinOpNode):
        return max(_get_max_window(node.left), _get_max_window(node.right))
    elif isinstance(node, FuncCallNode):
        inner_max = 0
        for arg in node.args:
            inner_max = max(inner_max, _get_max_window(arg))
        if node.name in WINDOW_FUNCTIONS and len(node.args) >= 2:
            n = _extract_number(node.args[1])
            if n is not None:
                return int(n) + inner_max
        return inner_max
    return 0


def _extract_number(node: ASTNode) -> Optional[float]:
    """从 AST 节点中提取数值（如果是 NumberNode）"""
    if isinstance(node, NumberNode):
        return node.value
    if isinstance(node, UnaryOpNode) and node.op == '-':
        v = _extract_number(node.operand)
        return -v if v is not None else None
    return None


def _extract_fields(node: ASTNode) -> list[str]:
    """递归提取 AST 中所有字段引用"""
    fields = []
    if isinstance(node, FieldNode):
        fields.append(node.name)
    elif isinstance(node, UnaryOpNode):
        fields.extend(_extract_fields(node.operand))
    elif isinstance(node, BinOpNode):
        fields.extend(_extract_fields(node.left))
        fields.extend(_extract_fields(node.right))
    elif isinstance(node, FuncCallNode):
        for arg in node.args:
            fields.extend(_extract_fields(arg))
    return fields


def _extract_functions(node: ASTNode) -> list[str]:
    """递归提取 AST 中所有函数调用"""
    funcs = []
    if isinstance(node, FuncCallNode):
        funcs.append(node.name)
        for arg in node.args:
            funcs.extend(_extract_functions(arg))
    elif isinstance(node, UnaryOpNode):
        funcs.extend(_extract_functions(node.operand))
    elif isinstance(node, BinOpNode):
        funcs.extend(_extract_functions(node.left))
        funcs.extend(_extract_functions(node.right))
    return funcs


def _could_be_zero(node: ASTNode) -> bool:
    """启发式检测：表达式是否可能为零"""
    if isinstance(node, NumberNode):
        return node.value == 0.0
    if isinstance(node, FieldNode):
        return node.name in ZERO_RISK_FIELDS
    if isinstance(node, UnaryOpNode):
        return _could_be_zero(node.operand)
    if isinstance(node, BinOpNode):
        if node.op == '-':
            # a - b 可能为零（a == b 时）
            return True
        return _could_be_zero(node.left) or _could_be_zero(node.right)
    if isinstance(node, FuncCallNode):
        return any(_could_be_zero(arg) for arg in node.args)
    return False


def _could_be_negative(node: ASTNode) -> bool:
    """启发式检测：表达式是否可能为负数"""
    if isinstance(node, NumberNode):
        return node.value < 0.0
    if isinstance(node, UnaryOpNode) and node.op == '-':
        return True
    if isinstance(node, BinOpNode):
        if node.op == '-':
            # a - b 可能为负（a < b 时）
            return True
        return _could_be_negative(node.left) or _could_be_negative(node.right)
    if isinstance(node, FuncCallNode):
        return any(_could_be_negative(arg) for arg in node.args)
    return False


# ============================================================
# FormulaParseResult
# ============================================================

@dataclass
class FormulaParseResult:
    """公式解析结果"""
    valid: bool
    ast: Optional[ASTNode] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    max_window: int = 0
    used_fields: list[str] = field(default_factory=list)
    used_functions: list[str] = field(default_factory=list)


# ============================================================
# FormulaParser 类
# ============================================================

class FormulaParser:
    """受限公式解析器
    
    使用 Lark LALR 解析器进行公式解析，并在解析后进行安全性验证。
    """

    def __init__(self):
        self.parser = Lark(GRAMMAR, start='start', parser='lalr')

    def parse(self, formula: str) -> FormulaParseResult:
        """解析公式字符串并返回 FormulaParseResult
        
        Args:
            formula: 因子公式字符串
            
        Returns:
            FormulaParseResult 包含解析状态、AST、错误和警告信息
        """
        result = FormulaParseResult(valid=False)

        if not formula or not formula.strip():
            result.errors.append('公式为空')
            return result

        # 语法解析
        try:
            tree = self.parser.parse(formula.strip())
            ast = FormulaTransformer().transform(tree)
            result.ast = ast
        except Exception as e:
            result.errors.append(f'语法解析错误: {e}')
            return result

        # 验证
        result = self.validate(result)
        return result

    def validate(self, result: FormulaParseResult) -> FormulaParseResult:
        """验证公式安全性
        
        检查项：
        1. 所有字段名在白名单内
        2. 所有函数名在白名单内
        3. delay(x, n) 中 n 必须 >= 0
        4. 滚动窗口函数参数为正整数
        5. 检查除零风险
        6. 检查 log/sqrt 参数可能为负的风险
        
        Args:
            result: 包含已解析 AST 的 FormulaParseResult
            
        Returns:
            更新后的 FormulaParseResult（含验证结果）
        """
        ast = result.ast
        if ast is None:
            result.errors.append('AST 为空，无法验证')
            result.valid = False
            return result

        errors = []
        warnings = []

        # 提取字段和函数
        fields = _extract_fields(ast)
        functions = _extract_functions(ast)

        # 1. 字段白名单检查
        unknown_fields = [f for f in fields if f not in FIELD_WHITELIST]
        if unknown_fields:
            errors.append(f'未识别的字段: {", ".join(sorted(set(unknown_fields)))}')

        # 2. 函数白名单检查
        unknown_funcs = [f for f in functions if f not in FUNCTION_WHITELIST]
        if unknown_funcs:
            errors.append(f'未识别的函数: {", ".join(sorted(set(unknown_funcs)))}')

        # 3 & 4. 函数参数检查 + 5 & 6. 风险检查
        self._validate_func_calls(ast, errors, warnings)
        # 5. 除零风险检查（顶层表达式）
        self._check_division_risk(ast, errors, warnings)

        # 计算最大窗口
        max_window = _get_max_window(ast)

        # 汇总
        result.errors = errors
        result.warnings = warnings
        result.max_window = max_window
        result.used_fields = sorted(set(fields))
        result.used_functions = sorted(set(functions))
        result.valid = len(errors) == 0

        return result

    def _validate_func_calls(self, node: ASTNode, errors: list, warnings: list):
        """递归遍历 AST，验证函数调用参数和风险"""
        if isinstance(node, FuncCallNode):
            self._check_func_args(node, errors, warnings)
            for arg in node.args:
                self._validate_func_calls(arg, errors, warnings)
        elif isinstance(node, UnaryOpNode):
            self._validate_func_calls(node.operand, errors, warnings)
        elif isinstance(node, BinOpNode):
            self._validate_func_calls(node.left, errors, warnings)
            self._validate_func_calls(node.right, errors, warnings)

    def _check_func_args(self, node: FuncCallNode, errors: list, warnings: list):
        """检查单个函数调用的参数合法性"""
        name = node.name
        args = node.args

        if name == 'delay':
            if len(args) >= 2:
                n = _extract_number(args[1])
                if n is not None and n < 0:
                    errors.append(f'delay(x, n) 中 n 必须 >= 0，当前为 {int(n)}')
            elif len(args) < 2:
                errors.append(f'delay(x, n) 缺少第二个参数 n')

        elif name in ('ts_mean', 'ts_sum', 'ts_std', 'ts_min', 'ts_max'):
            if len(args) >= 2:
                n = _extract_number(args[1])
                if n is not None:
                    if n <= 0:
                        errors.append(f'{name}(x, n) 中 n 必须为正整数，当前为 {int(n)}')
                    elif n != int(n):
                        errors.append(f'{name}(x, n) 中 n 必须为正整数，当前为 {n}')
            elif len(args) < 2:
                errors.append(f'{name}(x, n) 缺少第二个参数 n')

        elif name == 'log':
            if len(args) >= 1:
                if _could_be_negative(args[0]):
                    warnings.append(f'log(x) 的参数可能为负数，运行时可能产生 NaN')

        elif name == 'sqrt':
            if len(args) >= 1:
                if _could_be_negative(args[0]):
                    warnings.append(f'sqrt(x) 的参数可能为负数，运行时可能产生 NaN')

        # 除零风险检查（对所有除法节点进行，不在函数调用中检查）
        # 除法检查在 BinOpNode 中处理

        # 递归检查函数参数中的除法
        for arg in args:
            self._check_division_risk(arg, errors, warnings)

    def _check_division_risk(self, node: ASTNode, errors: list, warnings: list):
        """递归检查除法运算中的除零风险"""
        if isinstance(node, BinOpNode) and node.op == '/':
            if _could_be_zero(node.right):
                # 如果分母是常数 0，报错
                if isinstance(node.right, NumberNode) and node.right.value == 0.0:
                    errors.append('除零错误：分母为常数 0')
                else:
                    warnings.append('除零风险：分母可能为零，运行时可能产生异常或无穷大')
        elif isinstance(node, BinOpNode):
            self._check_division_risk(node.left, errors, warnings)
            self._check_division_risk(node.right, errors, warnings)
        elif isinstance(node, UnaryOpNode):
            self._check_division_risk(node.operand, errors, warnings)
        elif isinstance(node, FuncCallNode):
            for arg in node.args:
                self._check_division_risk(arg, errors, warnings)

    # ---- 对外辅助方法 ----

    def get_max_window(self, ast: ASTNode) -> int:
        """计算最大回看窗口"""
        return _get_max_window(ast)

    def extract_fields(self, ast: ASTNode) -> list[str]:
        """提取使用的字段"""
        return sorted(set(_extract_fields(ast)))

    def extract_functions(self, ast: ASTNode) -> list[str]:
        """提取使用的函数"""
        return sorted(set(_extract_functions(ast)))