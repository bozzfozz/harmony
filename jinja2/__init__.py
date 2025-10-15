from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
import re
from typing import Any


class TemplateSyntaxError(RuntimeError):
    pass


class UndefinedError(RuntimeError):
    pass


class SafeString(str):
    pass


def pass_context(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    setattr(wrapper, "_jinja_pass_context", True)
    setattr(wrapper, "_jinja_original", function)
    return wrapper


def contextfunction(function: Callable[..., Any]) -> Callable[..., Any]:
    return function


class FileSystemLoader:
    def __init__(self, searchpath: str | Path | Sequence[str | Path]) -> None:
        if isinstance(searchpath, Sequence) and not isinstance(searchpath, str | Path):
            paths = [Path(p) for p in searchpath]
        else:
            paths = [Path(searchpath)]
        self._paths = [p if p.is_absolute() else p.resolve() for p in paths]

    def get_source(
        self,
        environment: Environment,
        template: str,
    ) -> tuple[str, str, Callable[[], bool]]:  # type: ignore[name-defined]
        for base in self._paths:
            candidate = base / template
            if candidate.exists():
                source = candidate.read_text(encoding="utf-8")
                return source, str(candidate), lambda: False
        raise FileNotFoundError(template)


class RuntimeContext:
    def __init__(self, env: Environment, initial: Mapping[str, Any] | None = None) -> None:  # type: ignore[name-defined]
        self._env = env
        self._frames: list[dict[str, Any]] = [dict(initial or {})]

    def push(self, values: Mapping[str, Any] | None = None) -> None:
        self._frames.append(dict(values or {}))

    def pop(self) -> None:
        if len(self._frames) == 1:
            raise RuntimeError("Cannot pop the root context frame")
        self._frames.pop()

    def set(self, name: str, value: Any) -> None:
        self._frames[-1][name] = value

    def as_mapping(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        for frame in self._frames:
            mapping.update(frame)
        return mapping

    def _bind_value(self, value: Any) -> Any:
        if getattr(value, "_jinja_pass_context_bound", False):
            return value
        if getattr(value, "_jinja_pass_context", False):
            original = getattr(value, "_jinja_original", value)

            @wraps(original)
            def bound(*args: Any, **kwargs: Any) -> Any:
                return original(self.as_mapping(), *args, **kwargs)

            setattr(bound, "_jinja_pass_context_bound", True)
            return bound
        return value

    def resolve(self, expression: str) -> Any:
        namespace: dict[str, Any] = {}
        for frame in self._frames:
            for key, value in frame.items():
                namespace[key] = self._bind_value(value)
        for key, value in self._env.globals.items():
            namespace[key] = self._bind_value(value)
        try:
            return eval(expression, {"__builtins__": {}}, namespace)
        except NameError as exc:  # pragma: no cover - defensive
            raise UndefinedError(str(exc)) from exc

    def copy(self) -> RuntimeContext:
        namespace: dict[str, Any] = {}
        for frame in self._frames:
            namespace.update(frame)
        return RuntimeContext(self._env, namespace)

    @property
    def env(self) -> Environment:  # type: ignore[name-defined]
        return self._env


class Node:
    def render(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:  # type: ignore[name-defined]
        raise NotImplementedError


@dataclass(slots=True)
class TextNode(Node):
    text: str

    def render(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:  # type: ignore[name-defined]
        return self.text


@dataclass(slots=True)
class VariableNode(Node):
    expression: str
    is_safe: bool = False

    def render(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:  # type: ignore[name-defined]
        value = context.resolve(self.expression)
        if isinstance(value, SafeString):
            return str(value)
        return str(value)


@dataclass(slots=True)
class ImportNode(Node):
    template_name: str
    alias: str

    def render(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:  # type: ignore[name-defined]
        template = context.env.get_template(self.template_name)
        module = template.make_module(context)
        context.set(self.alias, module)
        return ""


@dataclass(slots=True)
class SetNode(Node):
    target: str
    expression: str

    def render(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:  # type: ignore[name-defined]
        value = context.resolve(self.expression)
        context.set(self.target, value)
        return ""


@dataclass(slots=True)
class ForNode(Node):
    targets: list[str]
    iterable: str
    body: list[Node]

    def render(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:  # type: ignore[name-defined]
        result: list[str] = []
        sequence = context.resolve(self.iterable)
        for item in sequence:
            context.push()
            try:
                if len(self.targets) == 1:
                    context.set(self.targets[0], item)
                else:
                    if not isinstance(item, Iterable):
                        raise TemplateSyntaxError(
                            "Iterable unpack expected for multiple loop targets",
                        )
                    values = list(item)
                    if len(values) != len(self.targets):
                        raise TemplateSyntaxError("Loop target length mismatch")
                    for target, value in zip(self.targets, values, strict=True):
                        context.set(target, value)
                for node in self.body:
                    result.append(node.render(context, blocks))
            finally:
                context.pop()
        return "".join(result)


@dataclass(slots=True)
class IfBranch:
    test: str | None
    body: list[Node]


@dataclass(slots=True)
class IfNode(Node):
    branches: list[IfBranch]

    def render(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:  # type: ignore[name-defined]
        for branch in self.branches:
            if branch.test is None or bool(context.resolve(branch.test)):
                return "".join(node.render(context, blocks) for node in branch.body)
        return ""


@dataclass(slots=True)
class BlockNode(Node):
    name: str
    body: list[Node]

    def render(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:  # type: ignore[name-defined]
        override = blocks.get(self.name)
        if override is not None and override is not self:
            return override.render_body(context, blocks)
        return self.render_body(context, blocks)

    def render_body(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:  # type: ignore[name-defined]
        return "".join(node.render(context, blocks) for node in self.body)


@dataclass(slots=True)
class Macro:
    name: str
    args: list[str]
    body: list[Node]

    def invoke(
        self,
        module: TemplateModule,
        parent_context: RuntimeContext,
        *args: Any,
        **kwargs: Any,
    ) -> str:  # type: ignore[name-defined]
        call_context = parent_context.copy()
        call_context.push(module.namespace)
        values = dict(zip(self.args, args, strict=True))
        values.update(kwargs)
        call_context.push(values)
        try:
            return "".join(node.render(call_context, module.blocks) for node in self.body)
        finally:
            call_context.pop()
            call_context.pop()


class TemplateModule:
    def __init__(self, template: Template, base_context: RuntimeContext) -> None:  # type: ignore[name-defined]
        self._template = template
        self._context = base_context.copy()
        self.blocks: dict[str, BlockNode] = {}
        for node in template.body:
            if isinstance(node, ImportNode):
                node.render(self._context, self.blocks)
        self.namespace: dict[str, Callable[..., str]] = {}
        for name, macro in template.macros.items():
            self.namespace[name] = self._make_callable(macro)

    def _make_callable(self, macro: Macro) -> Callable[..., str]:
        def _callable(*args: Any, **kwargs: Any) -> str:
            return macro.invoke(self, self._context, *args, **kwargs)

        return _callable

    def __getattr__(self, item: str) -> Any:
        try:
            return self.namespace[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc


class Template:
    def __init__(self, environment: Environment, name: str, source: str) -> None:  # type: ignore[name-defined]
        self.environment = environment
        self.name = name
        parser = Parser(source)
        self.body = parser.body
        self.macros = parser.macros
        self.blocks = parser.blocks
        self.parent = parser.parent

    def make_module(self, context: RuntimeContext) -> TemplateModule:
        return TemplateModule(self, context)

    def render(self, *args: Any, **kwargs: Any) -> str:
        if args and kwargs:
            raise TypeError(
                "Template.render accepts either a mapping or keyword arguments, not both",
            )
        if args:
            if len(args) != 1:
                raise TypeError("Template.render expected a single mapping argument")
            mapping = args[0]
            if not isinstance(mapping, Mapping):
                raise TypeError("Template.render positional argument must be a mapping")
            context_data = dict(mapping)
        else:
            context_data = dict(kwargs)

        runtime_context = RuntimeContext(self.environment, context_data)
        if self.parent is not None:
            for node in self.body:
                if isinstance(node, ImportNode | SetNode):
                    node.render(runtime_context, self.blocks)
            parent_template = self.environment.get_template(self.parent)
            block_map = dict(parent_template.blocks)
            block_map.update(self.blocks)
            return parent_template._render(runtime_context, block_map)
        block_map = dict(self.blocks)
        return self._render(runtime_context, block_map)

    def _render(self, context: RuntimeContext, blocks: dict[str, BlockNode]) -> str:
        output: list[str] = []
        for node in self.body:
            rendered = node.render(context, blocks)
            if rendered:
                output.append(rendered)
        return "".join(output)


class Environment:
    def __init__(self, *, loader: FileSystemLoader, autoescape: bool = True) -> None:
        self.loader = loader
        self.autoescape = autoescape
        self.globals: dict[str, Any] = {}

    def get_template(self, name: str) -> Template:
        source, filename, _ = self.loader.get_source(self, name)
        return Template(self, filename, source)


class Parser:
    _token_re = re.compile(r"({{.*?}}|{%-?.*?-?%}|{%.*?%})", re.S)

    def __init__(self, source: str) -> None:
        self.tokens = self._tokenize(source)
        self.position = 0
        self.body: list[Node] = []
        self.macros: dict[str, Macro] = {}
        self.blocks: dict[str, BlockNode] = {}
        self.parent: str | None = None
        self.body = self._parse_nodes()

    def _tokenize(self, source: str) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        index = 0
        strip_next_left = False
        for match in self._token_re.finditer(source):
            start, end = match.span()
            text = source[index:start]
            if strip_next_left:
                text = text.lstrip()
                strip_next_left = False
            if text:
                tokens.append(("text", text))
            token = match.group(0)
            strip_left = token.startswith('{%-')
            strip_right = token.endswith('-%}')
            inner = token[2:-2]
            content = inner.strip()
            if content.startswith('-'):
                content = content[1:].lstrip()
            if content.endswith('-'):
                content = content[:-1].rstrip()
            if strip_left and tokens and tokens[-1][0] == "text":
                tokens[-1] = ("text", tokens[-1][1].rstrip())
            if strip_right:
                strip_next_left = True
            if token.startswith('{{'):
                tokens.append(("var", content))
            else:
                tokens.append(("stmt", content))
            index = end
        tail = source[index:]
        if strip_next_left:
            tail = tail.lstrip()
        if tail:
            tokens.append(("text", tail))
        return tokens

    def _current(self) -> tuple[str, str] | None:
        if self.position >= len(self.tokens):
            return None
        return self.tokens[self.position]

    def _advance(self) -> tuple[str, str]:
        token = self.tokens[self.position]
        self.position += 1
        return token

    def _parse_nodes(self, stop: set[str] | None = None) -> list[Node]:
        nodes: list[Node] = []
        while True:
            token = self._current()
            if token is None:
                break
            typ, value = token
            keyword = value.split(None, 1)[0] if value.strip() else ""
            if typ == "stmt" and stop and keyword in stop:
                break
            self._advance()
            if typ == "text":
                nodes.append(TextNode(value))
            elif typ == "var":
                nodes.append(self._parse_variable(value))
            else:
                if keyword == "extends":
                    self.parent = self._parse_string_argument(value[len("extends"):].strip())
                elif keyword == "import":
                    nodes.append(self._parse_import(value))
                elif keyword == "macro":
                    macro = self._parse_macro(value)
                    self.macros[macro.name] = macro
                elif keyword == "block":
                    block = self._parse_block(value)
                    self.blocks[block.name] = block
                    nodes.append(block)
                elif keyword == "set":
                    nodes.append(self._parse_set(value))
                elif keyword == "if":
                    nodes.append(self._parse_if(value))
                elif keyword == "for":
                    nodes.append(self._parse_for(value))
                elif value in {"endblock", "endif", "endfor", "endmacro"}:
                    raise TemplateSyntaxError(f"Unexpected '{value}'")
                else:
                    raise TemplateSyntaxError(f"Unsupported statement: {value}")
        return nodes

    def _parse_variable(self, token: str) -> VariableNode:
        expression = token
        is_safe = False
        if "|" in token:
            expression, _, filter_name = token.partition("|")
            expression = expression.strip()
            filter_name = filter_name.strip()
            if filter_name == "safe":
                is_safe = True
            else:
                raise TemplateSyntaxError(f"Unsupported filter: {filter_name}")
        return VariableNode(expression.strip(), is_safe)

    def _parse_string_argument(self, token: str) -> str:
        token = token.strip()
        if token.startswith('"') and token.endswith('"'):
            return token[1:-1]
        if token.startswith("'") and token.endswith("'"):
            return token[1:-1]
        raise TemplateSyntaxError("String literal expected")

    def _parse_import(self, statement: str) -> ImportNode:
        parts = statement.split()
        if len(parts) != 4 or parts[2] != "as":
            raise TemplateSyntaxError("Invalid import syntax")
        template_name = self._parse_string_argument(parts[1])
        alias = parts[3]
        return ImportNode(template_name, alias)

    def _parse_macro(self, statement: str) -> Macro:
        name_and_args = statement[len("macro"):].strip()
        name, arg_list = self._parse_callable_signature(name_and_args)
        body = self._parse_nodes(stop={"endmacro"})
        end_token = self._advance()
        if end_token[1] != "endmacro":
            raise TemplateSyntaxError("Expected endmacro")
        return Macro(name, arg_list, body)

    def _parse_block(self, statement: str) -> BlockNode:
        name = statement[len("block"):].strip()
        if not name:
            raise TemplateSyntaxError("Block name required")
        body = self._parse_nodes(stop={"endblock"})
        end_token = self._advance()
        if end_token[1] != "endblock":
            raise TemplateSyntaxError("Expected endblock")
        return BlockNode(name, body)

    def _parse_if(self, statement: str) -> IfNode:
        branches: list[IfBranch] = []
        current_test = statement[len("if"):].strip()
        body = self._parse_nodes(stop={"elif", "else", "endif"})
        branches.append(IfBranch(current_test, body))
        while True:
            token = self._advance()
            if token[1] == "endif":
                break
            if token[1].startswith("elif"):
                test = token[1][len("elif"):].strip()
                body = self._parse_nodes(stop={"elif", "else", "endif"})
                branches.append(IfBranch(test, body))
            elif token[1] == "else":
                else_body = self._parse_nodes(stop={"endif"})
                branches.append(IfBranch(None, else_body))
                end_token = self._advance()
                if end_token[1] != "endif":
                    raise TemplateSyntaxError("Expected endif")
                break
            else:
                raise TemplateSyntaxError("Unexpected token in if block")
        return IfNode(branches)

    def _parse_for(self, statement: str) -> ForNode:
        segment = statement[len("for"):].strip()
        if " in " not in segment:
            raise TemplateSyntaxError("Invalid for-loop syntax")
        target_part, expr = segment.split(" in ", 1)
        targets = [part.strip() for part in target_part.split(",")]
        body = self._parse_nodes(stop={"endfor"})
        end_token = self._advance()
        if end_token[1] != "endfor":
            raise TemplateSyntaxError("Expected endfor")
        return ForNode(targets, expr.strip(), body)

    def _parse_set(self, statement: str) -> SetNode:
        remainder = statement[len("set"):].strip()
        if "=" not in remainder:
            raise TemplateSyntaxError("Invalid set syntax")
        target, expr = remainder.split("=", 1)
        return SetNode(target.strip(), expr.strip())

    def _parse_callable_signature(self, spec: str) -> tuple[str, list[str]]:
        if "(" not in spec or not spec.endswith(")"):
            raise TemplateSyntaxError("Invalid macro definition")
        name, rest = spec.split("(", 1)
        args_str = rest[:-1]
        args = [arg.strip() for arg in args_str.split(",") if arg.strip()]
        return name.strip(), args


__all__ = [
    "Environment",
    "FileSystemLoader",
    "Template",
    "TemplateModule",
    "SafeString",
    "TemplateSyntaxError",
    "UndefinedError",
]
