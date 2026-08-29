"""Restricted execution of user polars pipeline snippets."""
import ast
import builtins
import polars as pl

BUILTINS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
    "isinstance", "len", "list", "max", "min", "pow", "print", "range",
    "repr", "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
}
PL_FUNCS = {
    "col", "lit", "when", "sum", "mean", "count", "min", "max", "first",
    "last", "len", "all", "any", "int_range", "date_range", "struct",
    "list", "array", "concat", "concat_str", "sum_horizontal",
    "mean_horizontal", "select", "Utf8", "String", "Int64", "Int32",
    "Float64", "Float32", "Boolean", "Date", "Datetime", "Time", "Decimal",
    "Duration", "List", "Array", "Struct", "Null",
}
DF_METHODS = {
    "filter", "with_columns", "select", "group_by", "agg", "sort", "rename",
    "cast", "join", "unique", "pivot", "limit", "head", "tail", "slice",
    "drop", "drop_nulls", "drop_duplicates", "fill_null", "fill_nan",
    "sql", "melt", "explode", "unnest", "sample", "lazy", "collect",
    "group_by_dynamic", "hstack", "vstack", "transpose", "gather_every",
    "with_row_index", "partition_by", "describe", "schema", "count_rows",
}
EXPR_METHODS = {
    "alias", "sum", "mean", "median", "count", "min", "max", "first",
    "last", "std", "var", "n_unique", "unique", "value_counts", "round",
    "ceil", "floor", "abs", "log", "sqrt", "pow", "exp", "cast", "sign",
    "is_null", "is_not_null", "is_in", "is_between", "is_duplicated",
    "is_unique", "is_finite", "is_nan", "eq", "neq", "gt", "lt", "ge",
    "le", "not_", "and_", "or_", "xor", "fill_null", "fill_nan",
    "replace", "replace_all", "replace_strict", "clip", "clip_min",
    "clip_max", "shift", "diff", "cum_sum", "cum_count", "rank",
    "percent_rank", "over", "sort_by", "reverse", "implode", "explode",
    "flatten", "to_physical", "to_string", "to_datetime", "hash",
    "reshape", "slice", "head", "tail", "when", "then", "otherwise",
    "contains", "starts_with", "ends_with", "to_datetime", "to_date",
    "to_integer", "to_float", "strip_chars", "lowercase", "uppercase",
    "split", "extract", "count_matches", "concat", "len_chars",
    "year", "iso_year", "quarter", "month", "week", "week_day", "day",
    "hour", "minute", "second", "date", "truncate", "epoch", "offset_by",
    "total_days", "total_hours", "total_minutes", "total_seconds", "days",
    "hours", "minutes", "seconds",
    "get", "lengths", "gather", "unique", "arg_max", "arg_min", "join",
    "field", "rename_fields", "with_fields", "set_ordering",
    "has_expr", "root_names", "output_name", "eq", "ne",
    "keep", "suffix", "prefix", "to_lowercase", "to_uppercase",
    "upper", "lower", "strip", "startswith", "endswith", "format", "zfill",
    "items", "keys", "values", "append", "index",
}
FORBIDDEN = {
    "eval", "exec", "compile", "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr", "hasattr", "open", "input",
    "breakpoint", "help", "exit", "quit", "memoryview", "super", "type",
    "object", "callable", "__import__", "bytes", "bytearray", "complex",
    "frozenset", "id", "issubclass", "iter", "next", "slice", "map",
    "filter", "os", "sys", "subprocess", "shutil", "pathlib", "socket",
    "importlib", "builtins", "json",
}
CALLBACK_METHODS = {
    "map_elements", "map", "map_rows", "map_batches", "map_dict", "apply",
}
BLOCKED_NODES = (
    ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.Lambda,
    ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Raise,
    ast.Try, ast.TryStar, ast.With, ast.For, ast.While, ast.Yield,
    ast.YieldFrom, ast.Await, ast.Match, ast.NamedExpr, ast.Starred,
    ast.Delete, ast.Assert,
)


def check(code: str) -> ast.Module:
    """Validate the snippet and return the parsed tree, or raise ValueError."""
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, BLOCKED_NODES):
            raise ValueError(f"forbidden construct: {type(node).__name__}")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ValueError(f"forbidden attribute: {node.attr}")
            if node.attr in CALLBACK_METHODS:
                raise ValueError(f"forbidden method: {node.attr}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in FORBIDDEN or func.id not in BUILTINS:
                    raise ValueError(f"forbidden call: {func.id}")
            elif isinstance(func, ast.Attribute):
                if func.attr not in PL_FUNCS | DF_METHODS | EXPR_METHODS:
                    raise ValueError(f"forbidden call: {func.attr}")
            else:
                raise ValueError("unsupported call")
    return tree


def run(code: str, df: pl.DataFrame, in_var: str, out_var: str) -> pl.DataFrame:
    """Run the validated snippet on `df`, return the `out_var` dataframe."""
    tree = check(code)
    scope = {
        "pl": pl,
        in_var: df,
        "__builtins__": {n: getattr(builtins, n) for n in BUILTINS},
    }
    exec(compile(tree, "<kpi>", "exec"), scope)
    try:
        return scope[out_var]
    except KeyError:
        raise ValueError(f"output variable '{out_var}' is not defined")