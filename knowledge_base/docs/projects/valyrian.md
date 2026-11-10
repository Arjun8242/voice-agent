---
project_id: valyrian
status: runnable_not_deployed
---

# Valyrian — Tree-Walking Interpreter

## Overview

Valyrian is a tree-walking interpreted programming language built from scratch in Java. The project implements a language-processing pipeline from lexical analysis and parsing through AST evaluation, lexical scoping, closures, recursion, and runtime error reporting.

The goal was to understand how programming languages execute source code internally rather than relying on an existing compiler or interpreter framework. Valyrian is runnable from the terminal; it is not presented as a hosted or deployed application.

## Architecture

Valyrian uses a three-stage interpreter pipeline:

```text
Source file (.val) -> Scanner -> Tokens -> Parser -> AST -> Interpreter -> Output
```

### 1. Scanner / Lexer

The scanner reads source code character by character and produces token objects. A token records its token type, lexeme, literal value when applicable, and source line number. Lexical errors are reported with line information without requiring the scanner to abandon all remaining input immediately.

Relevant files:

- `lexer/Scanner.java`
- `lexer/Token.java`
- `lexer/TokenType.java`

### 2. Parser

The parser uses recursive-descent parsing with operator-precedence rules to turn tokens into expression and statement AST nodes.

Notable implementation details:

- Expression rules are arranged by precedence.
- `for` loops are desugared into `while` loops during parsing; the AST does not require a dedicated `Stmt.For` node.
- Panic-mode recovery uses a `synchronize()` routine to recover after syntax errors and continue finding additional parse errors where possible.

Relevant files:

- `parser/Parser.java`
- `ast/Expr.java`
- `ast/Stmt.java`

### 3. Interpreter / Evaluator

The interpreter walks the AST and evaluates expressions and statements. It uses the Visitor Pattern through `Expr.Visitor<Object>` and `Stmt.Visitor<Void>` interfaces, separating node structure from evaluation behaviour.

Lexical scope is implemented with parent-linked `Environment` objects. Functions are first-class values; `ValyrianFunction` captures the environment in which a function is declared, enabling closures to preserve access to enclosing variables. A dedicated `Return` control-flow exception transfers return values out of nested statement evaluation.

Relevant files:

- `interpreter/Interpreter.java`
- `interpreter/Environment.java`
- `interpreter/ValyrianCallable.java`
- `interpreter/ValyrianFunction.java`
- `runtime/Return.java`

## Language Features

### Data types

- Numbers represented as Java `Double` values.
- Strings.
- Booleans (`true` and `false`).
- `nil`.
- Arrays represented as `List<Object>`.

### Expressions and operators

- Arithmetic operators: `+`, `-`, `*`, `/`.
- String concatenation using `+`.
- Comparisons: `<`, `>`, `<=`, `>=`.
- Equality: `==`, `!=`.
- Logical `and` and `or` with short-circuit evaluation.
- Unary operators: `-` and `!`.

### Statements and control flow

- Variable declarations using `var`.
- `if` / `else` branches.
- `while` loops.
- `for` loops, lowered into `while` loops by the parser.
- Blocks and lexical scope.
- `print` statements.

### Functions, recursion, and closures

- First-class functions declared with `fun`.
- Explicit `return` statements.
- Recursive function calls.
- Closures capture the declaration environment, allowing nested functions to retain and mutate enclosing state after the outer function returns.
- Nested scopes and variable shadowing are supported.

### Arrays

Array literals use square brackets, for example `[10, 20, 30]`. The language supports indexing such as `arr[1]` and indexed assignment such as `arr[1] = 99`.

## Example Programs

### Recursion

```text
fun fib(n) {
  if (n <= 1) { return n; }
  return fib(n - 1) + fib(n - 2);
}

print fib(10); // 55
```

### Closures

```text
fun makeCounter() {
  var count = 0;
  fun increment() {
    count = count + 1;
    return count;
  }
  return increment;
}

var counter = makeCounter();
print counter(); // 1
print counter(); // 2
print counter(); // 3
```

### Arrays

```text
var arr = [10, 20, 30];
print arr[1]; // 20
arr[1] = 99;
print arr[1]; // 99
```

### `for` loop desugaring

```text
for (var i = 0; i < 3; i = i + 1) {
  print i;
}
// Prints 0, 1, 2
```

## Error Handling and CLI Exit Codes

The interpreter distinguishes command-line usage errors, lexical/syntax errors, and runtime errors. The documented exit codes are:

- `64`: CLI usage error.
- `65`: lexical or syntax error.
- `70`: runtime error.

Error messages include line information where relevant. Parse errors use a dedicated `ParseError`; runtime failures use `RuntimeError`. These error categories help callers and scripts distinguish invalid invocation, invalid source code, and failures during execution.

## Repository Structure

```text
src/main/java/com/valyrian/
├── Valyrian.java             # CLI entry point and pipeline coordinator
├── lexer/                    # Scanner, Token, TokenType
├── parser/                   # Recursive-descent parser
├── ast/                      # Expression and statement AST types
├── interpreter/              # Evaluator, environments, callable and function types
├── runtime/                  # Return control-flow mechanism
└── error/                    # ParseError and RuntimeError

docs/                         # Language specifications and task docs
tests/                        # .val test programs
build.gradle                  # Gradle build
```

## Test Coverage

The repository documents 17 `.val` test scripts covering areas such as:

- Operator precedence and expression evaluation.
- Variables, conditionals, loops, and loop desugaring.
- Arrays and indexed assignment.
- Functions, return values, and recursion.
- Closures and independent closure state.
- Variable shadowing across nested scopes.
- Short-circuit logical evaluation.
- Runtime errors, syntax errors, undefined-variable assignment, and early return behaviour.

These are only a runnable language-behaviour scripts not a particular unit-testing framework.

## Design Decisions and Trade-offs

- **Tree-walking evaluation:** evaluates the AST directly instead of generating machine code or bytecode. This keeps the implementation approachable and makes interpreter behaviour explicit, though it is not a compiled execution engine.
- **Recursive-descent parser:** expresses grammar rules as parser methods and makes precedence/control flow understandable, but grammar changes may require coordinated parser updates.
- **Visitor Pattern:** keeps expression/statement node definitions distinct from evaluation logic, although adding a new AST operation can require updating visitor interfaces and implementations.
- **Lexical environment chains:** provide nested scope lookup and closure capture; lookup may traverse parent environments.
- **`for` desugaring:** reuses `while` execution logic and avoids a separate `for` AST node.
- **Return exception:** uses a dedicated control-flow exception to unwind nested statement evaluation and deliver a return value.

## Scope and Limitations

Valyrian is a learning-oriented interpreter with a focused language feature set. The documented repository does not claim a production compiler, bytecode virtual machine, native-code generation, or a deployed hosted playground. Feature support should be described according to the language features listed above rather than assuming complete compatibility with Java, JavaScript, or another language.

## Project Links

- Repository and source: https://github.com/Arjun8242/Valyrian
- Run instructions: use the Gradle Wrapper from the repository root.
