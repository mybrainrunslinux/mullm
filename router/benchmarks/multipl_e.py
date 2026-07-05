"""
MultiPL-E benchmark — JavaScript, TypeScript, Go, C, C++, Java, Ruby, PHP, Lua, R, Rust, Julia, C#.

For each of 20 problems per language, posts a prompt to muLLM /query, extracts code
from the response, executes it in a subprocess sandbox, and reports pass@1.

Problem set: HumanEval problems translated to each language's idioms — same logic, target-language syntax.
Each problem embeds self-contained assertions so no external test harness is needed.

Executors:
  JS:     node -e "..."
  TS:     npx tsx -e "..."
  Go:     go run temp.go
  C:      gcc -o temp temp.c -lm && ./temp
  C++:    g++ -std=c++17 -o temp temp.cpp && ./temp
  Java:   javac + java
  Ruby:   /usr/bin/ruby temp.rb
  PHP:    /usr/bin/php temp.php
  Lua:    /usr/bin/lua temp.lua
  R:      /usr/bin/Rscript temp.R
  Rust:   ~/.cargo/bin/rustc -o temp temp.rs && ./temp
  Julia:  ~/.juliaup/bin/julia temp.jl
  C#:     dotnet run (net8.0 project)

Return format matches runner.py conventions:
  {
    "benchmark": "multipl_e",
    "pass_at_1": float,
    "passed": int,
    "total": int,
    "per_language": {"js": {...}, "ts": {...}, ...},
    "problems": [...],
  }
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any

import httpx

# ── Constants ─────────────────────────────────────────────────────────────────
MULLM_DEFAULT = "http://127.0.0.1:6856"
EXEC_TIMEOUT = 10  # seconds

# ── Problem definitions ────────────────────────────────────────────────────────
# Each problem: task_id, language, prompt (the function stub), test (assertions), entry_point
# For JS: the model returns a function body or full function; tests use console.assert + process.exit(1)
# For Go: the model returns the full function (possibly with package/imports); tests run in main()

_JS_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/js/0",
        "language": "js",
        "entry_point": "hasCloseElements",
        "prompt": (
            "// Complete this JavaScript function.\n"
            "// Return only the function body — no markdown, no explanation.\n\n"
            "/**\n"
            " * Check if any two numbers in the array are closer than threshold.\n"
            " * @param {number[]} numbers\n"
            " * @param {number} threshold\n"
            " * @returns {boolean}\n"
            " */\n"
            "function hasCloseElements(numbers, threshold) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (hasCloseElements([1.0,2.0,3.0], 0.5) !== false) { process.exit(1); }\n"
            "if (hasCloseElements([1.0,2.8,3.0,4.0,5.0,2.0], 0.3) !== true) { process.exit(1); }\n"
            "if (hasCloseElements([1.0,2.0,3.9,4.0,5.0,2.2], 0.3) !== true) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/2",
        "language": "js",
        "entry_point": "truncateNumber",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Return the decimal part of a positive float.\n"
            " * truncateNumber(3.5) === 0.5\n"
            " */\n"
            "function truncateNumber(number) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (Math.abs(truncateNumber(3.5) - 0.5) > 1e-9) { process.exit(1); }\n"
            "if (Math.abs(truncateNumber(1.33) - 0.33) > 1e-4) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/3",
        "language": "js",
        "entry_point": "belowZero",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Given a list of deposit/withdrawal ops on a zero-balance account,\n"
            " * return true if the balance ever drops below zero.\n"
            " * belowZero([1,2,3]) === false\n"
            " * belowZero([1,2,-4,5]) === true\n"
            " */\n"
            "function belowZero(operations) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (belowZero([1,2,3]) !== false) { process.exit(1); }\n"
            "if (belowZero([1,2,-4,5]) !== true) { process.exit(1); }\n"
            "if (belowZero([1,-1,2,-2,5,3,-3]) !== false) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/5",
        "language": "js",
        "entry_point": "intersperse",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Insert delimiter between every pair of consecutive elements.\n"
            " * intersperse([1,2,3], 4) === [1,4,2,4,3]\n"
            " */\n"
            "function intersperse(numbers, delimiter) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "const r1 = intersperse([1,2,3], 4);\n"
            "if (JSON.stringify(r1) !== JSON.stringify([1,4,2,4,3])) { process.exit(1); }\n"
            "if (JSON.stringify(intersperse([], 7)) !== '[]') { process.exit(1); }\n"
            "if (JSON.stringify(intersperse([1], 7)) !== '[1]') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/7",
        "language": "js",
        "entry_point": "filterBySubstring",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Filter an array of strings to those containing the given substring.\n"
            " * filterBySubstring(['abc','def','abcdef'], 'abc') === ['abc','abcdef']\n"
            " */\n"
            "function filterBySubstring(strings, substring) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "const r = filterBySubstring(['abc','def','abcdef'], 'abc');\n"
            "if (JSON.stringify(r) !== JSON.stringify(['abc','abcdef'])) { process.exit(1); }\n"
            "if (filterBySubstring([], 'x').length !== 0) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/8",
        "language": "js",
        "entry_point": "sumProduct",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Return [sum, product] of all integers in the list.\n"
            " * sumProduct([1,2,3,4]) === [10, 24]\n"
            " */\n"
            "function sumProduct(numbers) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "const [s, p] = sumProduct([1,2,3,4]);\n"
            "if (s !== 10 || p !== 24) { process.exit(1); }\n"
            "const [s2, p2] = sumProduct([]);\n"
            "if (s2 !== 0 || p2 !== 1) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/10",
        "language": "js",
        "entry_point": "makeStringPalindrome",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Find the shortest palindrome by appending characters to the end of s.\n"
            " * makePalindrome('') === ''\n"
            " * makePalindrome('cat') === 'catac'\n"
            " * makePalindrome('cata') === 'catac'\n"
            " */\n"
            "function makePalindrome(s) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (makePalindrome('') !== '') { process.exit(1); }\n"
            "if (makePalindrome('cat') !== 'catac') { process.exit(1); }\n"
            "if (makePalindrome('cata') !== 'catac') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/11",
        "language": "js",
        "entry_point": "stringXor",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * XOR two binary strings of equal length. '0' XOR '0' = '0', etc.\n"
            " * stringXor('010', '110') === '100'\n"
            " */\n"
            "function stringXor(a, b) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (stringXor('010', '110') !== '100') { process.exit(1); }\n"
            "if (stringXor('0101', '0000') !== '0101') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/12",
        "language": "js",
        "entry_point": "longest",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Return the longest string in the list, or null if empty.\n"
            " * longest(['a','bb','ccc']) === 'ccc'\n"
            " */\n"
            "function longest(strings) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (longest(['a','bb','ccc']) !== 'ccc') { process.exit(1); }\n"
            "if (longest([]) !== null) { process.exit(1); }\n"
            "if (longest(['a','b','c']) !== 'a') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/14",
        "language": "js",
        "entry_point": "allPrefixes",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Return all prefixes of s from shortest to longest.\n"
            " * allPrefixes('abc') === ['a','ab','abc']\n"
            " */\n"
            "function allPrefixes(s) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (JSON.stringify(allPrefixes('abc')) !== JSON.stringify(['a','ab','abc'])) { process.exit(1); }\n"
            "if (JSON.stringify(allPrefixes('')) !== '[]') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/15",
        "language": "js",
        "entry_point": "stringSequence",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Return a string of space-separated numbers from 0 to n (inclusive).\n"
            " * stringSequence(0) === '0'\n"
            " * stringSequence(5) === '0 1 2 3 4 5'\n"
            " */\n"
            "function stringSequence(n) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (stringSequence(0) !== '0') { process.exit(1); }\n"
            "if (stringSequence(5) !== '0 1 2 3 4 5') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/17",
        "language": "js",
        "entry_point": "parseMusic",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Parse a music string into beat counts.\n"
            " * 'o' = 4 beats, 'o|' = 2 beats, '.|' = 1 beat.\n"
            " * parseMusic('o o| .|') === [4, 2, 1]\n"
            " */\n"
            "function parseMusic(musicString) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (JSON.stringify(parseMusic('o o| .|')) !== JSON.stringify([4,2,1])) { process.exit(1); }\n"
            "if (JSON.stringify(parseMusic('')) !== '[]') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/19",
        "language": "js",
        "entry_point": "sortNumbers",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Sort a space-separated string of number words ('zero' through 'nine').\n"
            " * sortNumbers('three one five') === 'one three five'\n"
            " */\n"
            "function sortNumbers(numbers) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (sortNumbers('three one five') !== 'one three five') { process.exit(1); }\n"
            "if (sortNumbers('') !== '') { process.exit(1); }\n"
            "if (sortNumbers('nine zero') !== 'zero nine') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/20",
        "language": "js",
        "entry_point": "findClosestElements",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * From a sorted array of numbers, find the two closest elements.\n"
            " * Return them as [smaller, larger].\n"
            " * findClosestElements([1.0,2.0,3.0,4.0,5.0,2.2]) => [2.0, 2.2]\n"
            " */\n"
            "function findClosestElements(numbers) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "const r = findClosestElements([1.0,2.0,3.0,4.0,5.0,2.2]);\n"
            "if (Math.abs(r[0]-2.0)>1e-9 || Math.abs(r[1]-2.2)>1e-9) { process.exit(1); }\n"
            "const r2 = findClosestElements([1.0,2.0,3.0,4.0,5.0,2.0]);\n"
            "if (Math.abs(r2[0]-2.0)>1e-9 || Math.abs(r2[1]-2.0)>1e-9) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/21",
        "language": "js",
        "entry_point": "rescaleToUnit",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Rescale an array so min becomes 0.0 and max becomes 1.0.\n"
            " * rescaleToUnit([1.0,2.0,3.0,4.0,5.0]) => [0.0,0.25,0.5,0.75,1.0]\n"
            " */\n"
            "function rescaleToUnit(numbers) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "const r = rescaleToUnit([1.0,2.0,3.0,4.0,5.0]);\n"
            "const exp = [0.0,0.25,0.5,0.75,1.0];\n"
            "for (let i=0;i<exp.length;i++) { if (Math.abs(r[i]-exp[i])>1e-9) { process.exit(1); } }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/22",
        "language": "js",
        "entry_point": "filterIntegers",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Filter a mixed-type array to return only integers.\n"
            " * filterIntegers(['a', 3.14, 5, 'b', 6]) => [5, 6]\n"
            " */\n"
            "function filterIntegers(values) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "const r = filterIntegers(['a', 3.14, 5, 'b', 6]);\n"
            "if (JSON.stringify(r) !== JSON.stringify([5,6])) { process.exit(1); }\n"
            "if (filterIntegers([]).length !== 0) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/23",
        "language": "js",
        "entry_point": "strlen",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Return the length of a string.\n"
            " * strlen('') === 0, strlen('abc') === 3\n"
            " */\n"
            "function strlen(s) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (strlen('') !== 0) { process.exit(1); }\n"
            "if (strlen('abc') !== 3) { process.exit(1); }\n"
            "if (strlen('hello world') !== 11) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/26",
        "language": "js",
        "entry_point": "largestDivisor",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Return the largest divisor of n (not including n itself).\n"
            " * largestDivisor(15) === 5\n"
            " */\n"
            "function largestDivisor(n) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (largestDivisor(15) !== 5) { process.exit(1); }\n"
            "if (largestDivisor(27) !== 9) { process.exit(1); }\n"
            "if (largestDivisor(100) !== 50) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/27",
        "language": "js",
        "entry_point": "factorize",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Return the prime factorization of n as a sorted array.\n"
            " * factorize(8) === [2,2,2]\n"
            " * factorize(25) === [5,5]\n"
            " * factorize(70) === [2,5,7]\n"
            " */\n"
            "function factorize(n) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (JSON.stringify(factorize(8)) !== '[2,2,2]') { process.exit(1); }\n"
            "if (JSON.stringify(factorize(25)) !== '[5,5]') { process.exit(1); }\n"
            "if (JSON.stringify(factorize(70)) !== '[2,5,7]') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/js/32",
        "language": "js",
        "entry_point": "isPrime",
        "prompt": (
            "// Complete this JavaScript function.\n\n"
            "/**\n"
            " * Return true if n is a prime number.\n"
            " * isPrime(6) === false, isPrime(101) === true, isPrime(2) === true\n"
            " */\n"
            "function isPrime(n) {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (isPrime(6) !== false) { process.exit(1); }\n"
            "if (isPrime(101) !== true) { process.exit(1); }\n"
            "if (isPrime(11) !== true) { process.exit(1); }\n"
            "if (isPrime(13441) !== true) { process.exit(1); }\n"
            "if (isPrime(2) !== true) { process.exit(1); }\n"
        ),
    },
]

_GO_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/go/0",
        "language": "go",
        "entry_point": "hasCloseElements",
        "prompt": (
            "// Complete this Go function. Return the full compilable Go file with package main and imports.\n\n"
            "package main\n\n"
            "import (\n"
            '\t"fmt"\n'
            '\t"math"\n'
            ")\n\n"
            "// hasCloseElements checks if any two numbers differ by less than threshold.\n"
            "func hasCloseElements(numbers []float64, threshold float64) bool {\n"
            "\t// your code here\n"
            "\treturn false\n"
            "}\n\n"
            "func main() {\n"
            '\tif hasCloseElements([]float64{1.0,2.0,3.0}, 0.5) { panic("fail1") }\n'
            '\tif !hasCloseElements([]float64{1.0,2.8,3.0,4.0}, 0.3) { panic("fail2") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",  # test is embedded in the main() above
    },
    {
        "task_id": "MultiPL-E/go/2",
        "language": "go",
        "entry_point": "truncateNumber",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            "import (\n"
            '\t"fmt"\n'
            '\t"math"\n'
            ")\n\n"
            "// truncateNumber returns the decimal part of a positive float.\n"
            "func truncateNumber(number float64) float64 {\n"
            "\t// your code here\n"
            "\treturn 0\n"
            "}\n\n"
            "func main() {\n"
            '\tif math.Abs(truncateNumber(3.5)-0.5) > 1e-9 { panic("fail") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/3",
        "language": "go",
        "entry_point": "belowZero",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// belowZero returns true if the balance ever drops below zero.\n"
            "func belowZero(operations []int) bool {\n"
            "\t// your code here\n"
            "\treturn false\n"
            "}\n\n"
            "func main() {\n"
            '\tif !belowZero([]int{1,-2,4}) { panic("fail1") }\n'
            '\tif belowZero([]int{1,2,3}) { panic("fail2") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/5",
        "language": "go",
        "entry_point": "intersperse",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// intersperse inserts delimiter between every pair of consecutive elements.\n"
            "func intersperse(numbers []int, delimiter int) []int {\n"
            "\t// your code here\n"
            "\treturn nil\n"
            "}\n\n"
            "func main() {\n"
            "\tr := intersperse([]int{1,2,3}, 4)\n"
            "\texp := []int{1,4,2,4,3}\n"
            '\tfor i,v := range r { if v != exp[i] { panic(fmt.Sprintf("fail at %d",i)) } }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/7",
        "language": "go",
        "entry_point": "filterBySubstring",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            "import (\n"
            '\t"fmt"\n'
            '\t"strings"\n'
            ")\n\n"
            "// filterBySubstring filters strings containing the given substring.\n"
            "func filterBySubstring(strs []string, sub string) []string {\n"
            "\t// your code here\n"
            "\treturn nil\n"
            "}\n\n"
            "func main() {\n"
            '\tr := filterBySubstring([]string{"abc","def","abcdef"}, "abc")\n'
            '\tif len(r) != 2 { panic("fail len") }\n'
            "\tfor _,s := range r {\n"
            '\t\tif !strings.Contains(s, "abc") { panic("fail contains") }\n'
            "\t}\n"
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/8",
        "language": "go",
        "entry_point": "sumProduct",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// sumProduct returns the sum and product of all integers.\n"
            "func sumProduct(numbers []int) (int, int) {\n"
            "\t// your code here\n"
            "\treturn 0, 0\n"
            "}\n\n"
            "func main() {\n"
            "\ts, p := sumProduct([]int{1,2,3,4})\n"
            '\tif s != 10 || p != 24 { panic("fail") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/11",
        "language": "go",
        "entry_point": "stringXor",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// stringXor XORs two equal-length binary strings.\n"
            "func stringXor(a, b string) string {\n"
            "\t// your code here\n"
            '\treturn ""\n'
            "}\n\n"
            "func main() {\n"
            '\tif stringXor("010","110") != "100" { panic("fail1") }\n'
            '\tif stringXor("0101","0000") != "0101" { panic("fail2") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/12",
        "language": "go",
        "entry_point": "longest",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// longest returns the longest string (empty string if list is empty).\n"
            "func longest(strs []string) string {\n"
            "\t// your code here\n"
            '\treturn ""\n'
            "}\n\n"
            "func main() {\n"
            '\tif longest([]string{"a","bb","ccc"}) != "ccc" { panic("fail1") }\n'
            '\tif longest([]string{}) != "" { panic("fail2") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/14",
        "language": "go",
        "entry_point": "allPrefixes",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// allPrefixes returns all prefixes of s from shortest to longest.\n"
            "func allPrefixes(s string) []string {\n"
            "\t// your code here\n"
            "\treturn nil\n"
            "}\n\n"
            "func main() {\n"
            '\tr := allPrefixes("abc")\n'
            '\tif r[0] != "a" || r[1] != "ab" || r[2] != "abc" { panic("fail") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/15",
        "language": "go",
        "entry_point": "stringSequence",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            "import (\n"
            '\t"fmt"\n'
            '\t"strings"\n'
            '\t"strconv"\n'
            ")\n\n"
            "// stringSequence returns '0 1 2 ... n'.\n"
            "func stringSequence(n int) string {\n"
            "\t// your code here\n"
            '\treturn ""\n'
            "}\n\n"
            "func main() {\n"
            '\tif stringSequence(0) != "0" { panic("fail1") }\n'
            '\tif stringSequence(5) != "0 1 2 3 4 5" { panic("fail2") }\n'
            '\t_ = strings.Join([]string{}, " ")\n'
            "\t_ = strconv.Itoa(0)\n"
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/17",
        "language": "go",
        "entry_point": "parseMusic",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            "import (\n"
            '\t"fmt"\n'
            '\t"strings"\n'
            ")\n\n"
            "// parseMusic maps 'o'->4, 'o|'->2, '.|'->1.\n"
            "func parseMusic(s string) []int {\n"
            "\t// your code here\n"
            "\treturn nil\n"
            "}\n\n"
            "func main() {\n"
            '\tr := parseMusic("o o| .|")\n'
            '\tif len(r) != 3 || r[0] != 4 || r[1] != 2 || r[2] != 1 { panic("fail") }\n'
            "\t_ = strings.Fields\n"
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/22",
        "language": "go",
        "entry_point": "strlen",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// strlen returns the length of the string.\n"
            "func strlen(s string) int {\n"
            "\t// your code here\n"
            "\treturn 0\n"
            "}\n\n"
            "func main() {\n"
            '\tif strlen("") != 0 { panic("fail1") }\n'
            '\tif strlen("abc") != 3 { panic("fail2") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/26",
        "language": "go",
        "entry_point": "largestDivisor",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// largestDivisor returns the largest divisor of n less than n.\n"
            "func largestDivisor(n int) int {\n"
            "\t// your code here\n"
            "\treturn 0\n"
            "}\n\n"
            "func main() {\n"
            '\tif largestDivisor(15) != 5 { panic("fail1") }\n'
            '\tif largestDivisor(27) != 9 { panic("fail2") }\n'
            '\tif largestDivisor(100) != 50 { panic("fail3") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/27",
        "language": "go",
        "entry_point": "factorize",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// factorize returns the prime factorization of n as a sorted slice.\n"
            "func factorize(n int) []int {\n"
            "\t// your code here\n"
            "\treturn nil\n"
            "}\n\n"
            "func main() {\n"
            "\tr := factorize(8)\n"
            "\texp := []int{2,2,2}\n"
            '\tif len(r) != len(exp) { panic(fmt.Sprintf("fail len %v",r)) }\n'
            '\tfor i,v := range r { if v != exp[i] { panic("fail values") } }\n'
            "\tr2 := factorize(70)\n"
            "\texp2 := []int{2,5,7}\n"
            '\tif len(r2) != len(exp2) { panic(fmt.Sprintf("fail2 len %v",r2)) }\n'
            '\tfor i,v := range r2 { if v != exp2[i] { panic("fail2 values") } }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/32",
        "language": "go",
        "entry_point": "isPrime",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// isPrime returns true if n is prime.\n"
            "func isPrime(n int) bool {\n"
            "\t// your code here\n"
            "\treturn false\n"
            "}\n\n"
            "func main() {\n"
            '\tif isPrime(6) { panic("fail1") }\n'
            '\tif !isPrime(101) { panic("fail2") }\n'
            '\tif !isPrime(2) { panic("fail3") }\n'
            '\tif !isPrime(11) { panic("fail4") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/33",
        "language": "go",
        "entry_point": "filterOdd",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// filterOdd returns only the odd numbers from the list.\n"
            "func filterOdd(xs []int) []int {\n"
            "\t// your code here\n"
            "\treturn nil\n"
            "}\n\n"
            "func main() {\n"
            "\tr := filterOdd([]int{1,2,3,4,5,6,7,8,9})\n"
            '\tif len(r) != 5 { panic(fmt.Sprintf("fail len=%d",len(r))) }\n'
            "\tfor _,v := range r {\n"
            '\t\tif v%2 == 0 { panic("fail even found") }\n'
            "\t}\n"
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/34",
        "language": "go",
        "entry_point": "countDigits",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            "import (\n"
            '\t"fmt"\n'
            '\t"unicode"\n'
            ")\n\n"
            "// countDigits counts the number of digit characters in a string.\n"
            "func countDigits(s string) int {\n"
            "\t// your code here\n"
            "\treturn 0\n"
            "}\n\n"
            "func main() {\n"
            '\tif countDigits("abc123def456") != 6 { panic("fail1") }\n'
            '\tif countDigits("") != 0 { panic("fail2") }\n'
            '\tif countDigits("no digits here") != 0 { panic("fail3") }\n'
            "\t_ = unicode.IsDigit\n"
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/35",
        "language": "go",
        "entry_point": "fibonacciN",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// fibonacciN returns the nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1).\n"
            "func fibonacciN(n int) int {\n"
            "\t// your code here\n"
            "\treturn 0\n"
            "}\n\n"
            "func main() {\n"
            '\tif fibonacciN(0) != 0 { panic("fail0") }\n'
            '\tif fibonacciN(1) != 1 { panic("fail1") }\n'
            '\tif fibonacciN(10) != 55 { panic("fail10") }\n'
            '\tif fibonacciN(20) != 6765 { panic("fail20") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/36",
        "language": "go",
        "entry_point": "reverseString",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            'import "fmt"\n\n'
            "// reverseString returns the reversed version of s.\n"
            "func reverseString(s string) string {\n"
            "\t// your code here\n"
            '\treturn ""\n'
            "}\n\n"
            "func main() {\n"
            '\tif reverseString("hello") != "olleh" { panic("fail1") }\n'
            '\tif reverseString("") != "" { panic("fail2") }\n'
            '\tif reverseString("a") != "a" { panic("fail3") }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/go/37",
        "language": "go",
        "entry_point": "unique",
        "prompt": (
            "// Complete this Go function. Return a full compilable Go file.\n\n"
            "package main\n\n"
            "import (\n"
            '\t"fmt"\n'
            '\t"sort"\n'
            ")\n\n"
            "// unique returns the sorted unique values from a list of integers.\n"
            "func unique(lst []int) []int {\n"
            "\t// your code here\n"
            "\treturn nil\n"
            "}\n\n"
            "func main() {\n"
            "\tr := unique([]int{5,3,5,2,3,3,9,0,123})\n"
            "\texp := []int{0,2,3,5,9,123}\n"
            "\t_ = sort.Ints\n"
            '\tif len(r) != len(exp) { panic(fmt.Sprintf("fail len=%d",len(r))) }\n'
            '\tfor i,v := range r { if v != exp[i] { panic(fmt.Sprintf("fail[%d]=%d",i,v)) } }\n'
            '\tfmt.Println("PASS")\n'
            "}\n"
        ),
        "test": "",
    },
]

_TS_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/ts/0",
        "language": "ts",
        "entry_point": "hasCloseElements",
        "prompt": (
            "// Complete this TypeScript function.\n"
            "// Return only the function body — no markdown, no explanation.\n\n"
            "function hasCloseElements(numbers: number[], threshold: number): boolean {\n"
            "  // your code here\n"
            "}\n"
        ),
        "test": (
            "if (hasCloseElements([1.0,2.0,3.0], 0.5) !== false) { process.exit(1); }\n"
            "if (hasCloseElements([1.0,2.8,3.0,4.0,5.0,2.0], 0.3) !== true) { process.exit(1); }\n"
            "if (hasCloseElements([1.0,2.0,3.9,4.0,5.0,2.2], 0.3) !== true) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/2",
        "language": "ts",
        "entry_point": "truncateNumber",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function truncateNumber(num: number): number {\n"
            "  // Return the decimal part of a positive float.\n"
            "  // truncateNumber(3.5) === 0.5\n"
            "}\n"
        ),
        "test": (
            "if (Math.abs(truncateNumber(3.5) - 0.5) > 1e-9) { process.exit(1); }\n"
            "if (Math.abs(truncateNumber(1.33) - 0.33) > 1e-4) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/3",
        "language": "ts",
        "entry_point": "belowZero",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function belowZero(operations: number[]): boolean {\n"
            "  // Return true if the running balance ever drops below zero.\n"
            "  // belowZero([1,2,-4,5]) === true\n"
            "}\n"
        ),
        "test": (
            "if (belowZero([1,2,3]) !== false) { process.exit(1); }\n"
            "if (belowZero([1,2,-4,5]) !== true) { process.exit(1); }\n"
            "if (belowZero([1,-1,2,-2,5,3,-3]) !== false) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/5",
        "language": "ts",
        "entry_point": "intersperse",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function intersperse(numbers: number[], delimiter: number): number[] {\n"
            "  // Insert delimiter between every pair of consecutive elements.\n"
            "  // intersperse([1,2,3], 4) === [1,4,2,4,3]\n"
            "}\n"
        ),
        "test": (
            "const r1 = intersperse([1,2,3], 4);\n"
            "if (JSON.stringify(r1) !== JSON.stringify([1,4,2,4,3])) { process.exit(1); }\n"
            "if (JSON.stringify(intersperse([], 7)) !== '[]') { process.exit(1); }\n"
            "if (JSON.stringify(intersperse([1], 7)) !== '[1]') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/7",
        "language": "ts",
        "entry_point": "filterBySubstring",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function filterBySubstring(strings: string[], substring: string): string[] {\n"
            "  // Filter strings containing the given substring.\n"
            "}\n"
        ),
        "test": (
            "const r = filterBySubstring(['abc','def','abcdef'], 'abc');\n"
            "if (JSON.stringify(r) !== JSON.stringify(['abc','abcdef'])) { process.exit(1); }\n"
            "if (filterBySubstring([], 'x').length !== 0) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/8",
        "language": "ts",
        "entry_point": "sumProduct",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function sumProduct(numbers: number[]): [number, number] {\n"
            "  // Return [sum, product] of all integers. Empty list => [0, 1].\n"
            "}\n"
        ),
        "test": (
            "const [s, p] = sumProduct([1,2,3,4]);\n"
            "if (s !== 10 || p !== 24) { process.exit(1); }\n"
            "const [s2, p2] = sumProduct([]);\n"
            "if (s2 !== 0 || p2 !== 1) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/10",
        "language": "ts",
        "entry_point": "makePalindrome",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function makePalindrome(s: string): string {\n"
            "  // Find the shortest palindrome by appending chars to end.\n"
            "  // makePalindrome('cat') === 'catac'\n"
            "}\n"
        ),
        "test": (
            "if (makePalindrome('') !== '') { process.exit(1); }\n"
            "if (makePalindrome('cat') !== 'catac') { process.exit(1); }\n"
            "if (makePalindrome('cata') !== 'catac') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/11",
        "language": "ts",
        "entry_point": "stringXor",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function stringXor(a: string, b: string): string {\n"
            "  // XOR two equal-length binary strings.\n"
            "  // stringXor('010', '110') === '100'\n"
            "}\n"
        ),
        "test": (
            "if (stringXor('010', '110') !== '100') { process.exit(1); }\n"
            "if (stringXor('0101', '0000') !== '0101') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/12",
        "language": "ts",
        "entry_point": "longest",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function longest(strings: string[]): string | null {\n"
            "  // Return the longest string, or null if empty.\n"
            "}\n"
        ),
        "test": (
            "if (longest(['a','bb','ccc']) !== 'ccc') { process.exit(1); }\n"
            "if (longest([]) !== null) { process.exit(1); }\n"
            "if (longest(['a','b','c']) !== 'a') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/14",
        "language": "ts",
        "entry_point": "allPrefixes",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function allPrefixes(s: string): string[] {\n"
            "  // Return all prefixes from shortest to longest.\n"
            "  // allPrefixes('abc') === ['a','ab','abc']\n"
            "}\n"
        ),
        "test": (
            "if (JSON.stringify(allPrefixes('abc')) !== JSON.stringify(['a','ab','abc'])) { process.exit(1); }\n"
            "if (JSON.stringify(allPrefixes('')) !== '[]') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/15",
        "language": "ts",
        "entry_point": "stringSequence",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function stringSequence(n: number): string {\n"
            "  // Return '0 1 2 ... n'.\n"
            "  // stringSequence(5) === '0 1 2 3 4 5'\n"
            "}\n"
        ),
        "test": (
            "if (stringSequence(0) !== '0') { process.exit(1); }\n"
            "if (stringSequence(5) !== '0 1 2 3 4 5') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/17",
        "language": "ts",
        "entry_point": "parseMusic",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function parseMusic(musicString: string): number[] {\n"
            "  // 'o' = 4 beats, 'o|' = 2, '.|' = 1. Parse space-separated.\n"
            "}\n"
        ),
        "test": (
            "if (JSON.stringify(parseMusic('o o| .|')) !== JSON.stringify([4,2,1])) { process.exit(1); }\n"
            "if (JSON.stringify(parseMusic('')) !== '[]') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/19",
        "language": "ts",
        "entry_point": "sortNumbers",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function sortNumbers(numbers: string): string {\n"
            "  // Sort space-separated number words ('zero' through 'nine').\n"
            "  // sortNumbers('three one five') === 'one three five'\n"
            "}\n"
        ),
        "test": (
            "if (sortNumbers('three one five') !== 'one three five') { process.exit(1); }\n"
            "if (sortNumbers('') !== '') { process.exit(1); }\n"
            "if (sortNumbers('nine zero') !== 'zero nine') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/20",
        "language": "ts",
        "entry_point": "findClosestElements",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function findClosestElements(numbers: number[]): [number, number] {\n"
            "  // Find the two closest elements, return [smaller, larger].\n"
            "}\n"
        ),
        "test": (
            "const r = findClosestElements([1.0,2.0,3.0,4.0,5.0,2.2]);\n"
            "if (Math.abs(r[0]-2.0)>1e-9 || Math.abs(r[1]-2.2)>1e-9) { process.exit(1); }\n"
            "const r2 = findClosestElements([1.0,2.0,3.0,4.0,5.0,2.0]);\n"
            "if (Math.abs(r2[0]-2.0)>1e-9 || Math.abs(r2[1]-2.0)>1e-9) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/21",
        "language": "ts",
        "entry_point": "rescaleToUnit",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function rescaleToUnit(numbers: number[]): number[] {\n"
            "  // Rescale so min=0.0, max=1.0.\n"
            "}\n"
        ),
        "test": (
            "const r = rescaleToUnit([1.0,2.0,3.0,4.0,5.0]);\n"
            "const exp = [0.0,0.25,0.5,0.75,1.0];\n"
            "for (let i=0;i<exp.length;i++) { if (Math.abs(r[i]-exp[i])>1e-9) { process.exit(1); } }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/22",
        "language": "ts",
        "entry_point": "filterIntegers",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function filterIntegers(values: any[]): number[] {\n"
            "  // Return only the integers from a mixed-type array.\n"
            "}\n"
        ),
        "test": (
            "const r = filterIntegers(['a', 3.14, 5, 'b', 6]);\n"
            "if (JSON.stringify(r) !== JSON.stringify([5,6])) { process.exit(1); }\n"
            "if (filterIntegers([]).length !== 0) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/23",
        "language": "ts",
        "entry_point": "strlen",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function strlen(s: string): number {\n"
            "  // Return the length of the string.\n"
            "}\n"
        ),
        "test": (
            "if (strlen('') !== 0) { process.exit(1); }\n"
            "if (strlen('abc') !== 3) { process.exit(1); }\n"
            "if (strlen('hello world') !== 11) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/26",
        "language": "ts",
        "entry_point": "largestDivisor",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function largestDivisor(n: number): number {\n"
            "  // Return the largest divisor of n (not n itself).\n"
            "}\n"
        ),
        "test": (
            "if (largestDivisor(15) !== 5) { process.exit(1); }\n"
            "if (largestDivisor(27) !== 9) { process.exit(1); }\n"
            "if (largestDivisor(100) !== 50) { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/27",
        "language": "ts",
        "entry_point": "factorize",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function factorize(n: number): number[] {\n"
            "  // Return prime factorization as sorted array.\n"
            "  // factorize(8) === [2,2,2], factorize(70) === [2,5,7]\n"
            "}\n"
        ),
        "test": (
            "if (JSON.stringify(factorize(8)) !== '[2,2,2]') { process.exit(1); }\n"
            "if (JSON.stringify(factorize(25)) !== '[5,5]') { process.exit(1); }\n"
            "if (JSON.stringify(factorize(70)) !== '[2,5,7]') { process.exit(1); }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ts/32",
        "language": "ts",
        "entry_point": "isPrime",
        "prompt": (
            "// Complete this TypeScript function.\n\n"
            "function isPrime(n: number): boolean {\n"
            "  // Return true if n is a prime number.\n"
            "}\n"
        ),
        "test": (
            "if (isPrime(6) !== false) { process.exit(1); }\n"
            "if (isPrime(101) !== true) { process.exit(1); }\n"
            "if (isPrime(11) !== true) { process.exit(1); }\n"
            "if (isPrime(13441) !== true) { process.exit(1); }\n"
            "if (isPrime(2) !== true) { process.exit(1); }\n"
        ),
    },
]

_C_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/c/0",
        "language": "c",
        "entry_point": "has_close_elements",
        "prompt": (
            "// Complete this C function. Return a full compilable C program with includes and main().\n\n"
            "#include <stdio.h>\n"
            "#include <stdlib.h>\n"
            "#include <math.h>\n"
            "#include <assert.h>\n\n"
            "// Return 1 if any two numbers in arr differ by less than threshold.\n"
            "int has_close_elements(double *arr, int n, double threshold) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    double a1[] = {1.0,2.0,3.0};\n"
            "    assert(has_close_elements(a1, 3, 0.5) == 0);\n"
            "    double a2[] = {1.0,2.8,3.0,4.0,5.0,2.0};\n"
            "    assert(has_close_elements(a2, 6, 0.3) == 1);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/2",
        "language": "c",
        "entry_point": "truncate_number",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <math.h>\n"
            "#include <assert.h>\n\n"
            "// Return the decimal part of a positive float.\n"
            "double truncate_number(double number) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(fabs(truncate_number(3.5) - 0.5) < 1e-9);\n"
            "    assert(fabs(truncate_number(1.33) - 0.33) < 1e-4);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/3",
        "language": "c",
        "entry_point": "below_zero",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Return 1 if balance ever drops below zero.\n"
            "int below_zero(int *ops, int n) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    int a1[] = {1,2,3};\n"
            "    assert(below_zero(a1, 3) == 0);\n"
            "    int a2[] = {1,2,-4,5};\n"
            "    assert(below_zero(a2, 4) == 1);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/5",
        "language": "c",
        "entry_point": "intersperse",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <stdlib.h>\n"
            "#include <assert.h>\n\n"
            "// Insert delimiter between every pair of consecutive elements.\n"
            "// Write result into out[], return the length of the result.\n"
            "int intersperse(int *nums, int n, int delimiter, int *out) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    int nums[] = {1,2,3};\n"
            "    int out[10];\n"
            "    int len = intersperse(nums, 3, 4, out);\n"
            "    assert(len == 5);\n"
            "    int exp[] = {1,4,2,4,3};\n"
            "    for (int i = 0; i < 5; i++) assert(out[i] == exp[i]);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/8",
        "language": "c",
        "entry_point": "sum_product",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Compute sum and product of array elements.\n"
            "void sum_product(int *arr, int n, int *sum_out, int *prod_out) {\n"
            "    // your code here\n"
            "}\n\n"
            "int main() {\n"
            "    int arr[] = {1,2,3,4};\n"
            "    int s, p;\n"
            "    sum_product(arr, 4, &s, &p);\n"
            "    assert(s == 10 && p == 24);\n"
            "    int empty[] = {};\n"
            "    sum_product(empty, 0, &s, &p);\n"
            "    assert(s == 0 && p == 1);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/11",
        "language": "c",
        "entry_point": "string_xor",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <string.h>\n"
            "#include <assert.h>\n\n"
            "// XOR two equal-length binary strings into result buffer.\n"
            "void string_xor(const char *a, const char *b, char *result) {\n"
            "    // your code here\n"
            "}\n\n"
            "int main() {\n"
            "    char r[100];\n"
            '    string_xor("010", "110", r);\n'
            '    assert(strcmp(r, "100") == 0);\n'
            '    string_xor("0101", "0000", r);\n'
            '    assert(strcmp(r, "0101") == 0);\n'
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/12",
        "language": "c",
        "entry_point": "longest",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <string.h>\n"
            "#include <assert.h>\n\n"
            "// Return pointer to the longest string, or NULL if n==0.\n"
            "const char* longest(const char **strs, int n) {\n"
            "    // your code here\n"
            "    return NULL;\n"
            "}\n\n"
            "int main() {\n"
            '    const char *a[] = {"a", "bb", "ccc"};\n'
            '    assert(strcmp(longest(a, 3), "ccc") == 0);\n'
            "    assert(longest(NULL, 0) == NULL);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/15",
        "language": "c",
        "entry_point": "string_sequence",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <string.h>\n"
            "#include <assert.h>\n\n"
            "// Write '0 1 2 ... n' into buffer.\n"
            "void string_sequence(int n, char *buf) {\n"
            "    // your code here\n"
            "}\n\n"
            "int main() {\n"
            "    char buf[200];\n"
            "    string_sequence(0, buf);\n"
            '    assert(strcmp(buf, "0") == 0);\n'
            "    string_sequence(5, buf);\n"
            '    assert(strcmp(buf, "0 1 2 3 4 5") == 0);\n'
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/23",
        "language": "c",
        "entry_point": "my_strlen",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Return the length of string s (without using strlen).\n"
            "int my_strlen(const char *s) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            '    assert(my_strlen("") == 0);\n'
            '    assert(my_strlen("abc") == 3);\n'
            '    assert(my_strlen("hello world") == 11);\n'
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/26",
        "language": "c",
        "entry_point": "largest_divisor",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Return the largest divisor of n less than n.\n"
            "int largest_divisor(int n) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(largest_divisor(15) == 5);\n"
            "    assert(largest_divisor(27) == 9);\n"
            "    assert(largest_divisor(100) == 50);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/27",
        "language": "c",
        "entry_point": "factorize",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Return prime factors of n into out[], return the count.\n"
            "int factorize(int n, int *out) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    int out[50];\n"
            "    int len = factorize(8, out);\n"
            "    assert(len == 3 && out[0]==2 && out[1]==2 && out[2]==2);\n"
            "    len = factorize(70, out);\n"
            "    assert(len == 3 && out[0]==2 && out[1]==5 && out[2]==7);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/32",
        "language": "c",
        "entry_point": "is_prime",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Return 1 if n is prime, 0 otherwise.\n"
            "int is_prime(int n) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(is_prime(6) == 0);\n"
            "    assert(is_prime(101) == 1);\n"
            "    assert(is_prime(11) == 1);\n"
            "    assert(is_prime(2) == 1);\n"
            "    assert(is_prime(13441) == 1);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/33",
        "language": "c",
        "entry_point": "filter_odd",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Copy only odd numbers from src to dst, return count.\n"
            "int filter_odd(int *src, int n, int *dst) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    int src[] = {1,2,3,4,5,6,7,8,9};\n"
            "    int dst[10];\n"
            "    int cnt = filter_odd(src, 9, dst);\n"
            "    assert(cnt == 5);\n"
            "    for (int i = 0; i < cnt; i++) assert(dst[i] % 2 == 1);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/34",
        "language": "c",
        "entry_point": "count_digits",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <ctype.h>\n"
            "#include <assert.h>\n\n"
            "// Count digit characters in a string.\n"
            "int count_digits(const char *s) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            '    assert(count_digits("abc123def456") == 6);\n'
            '    assert(count_digits("") == 0);\n'
            '    assert(count_digits("no digits here") == 0);\n'
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/35",
        "language": "c",
        "entry_point": "fibonacci",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Return the nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1).\n"
            "int fibonacci(int n) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(fibonacci(0) == 0);\n"
            "    assert(fibonacci(1) == 1);\n"
            "    assert(fibonacci(10) == 55);\n"
            "    assert(fibonacci(20) == 6765);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/36",
        "language": "c",
        "entry_point": "reverse_string",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <string.h>\n"
            "#include <assert.h>\n\n"
            "// Reverse string in-place.\n"
            "void reverse_string(char *s) {\n"
            "    // your code here\n"
            "}\n\n"
            "int main() {\n"
            '    char s1[] = "hello";\n'
            "    reverse_string(s1);\n"
            '    assert(strcmp(s1, "olleh") == 0);\n'
            '    char s2[] = "";\n'
            "    reverse_string(s2);\n"
            '    assert(strcmp(s2, "") == 0);\n'
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/37",
        "language": "c",
        "entry_point": "unique_sorted",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <stdlib.h>\n"
            "#include <assert.h>\n\n"
            "// Copy unique values from src into dst in sorted order, return count.\n"
            "int unique_sorted(int *src, int n, int *dst) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    int src[] = {5,3,5,2,3,3,9,0,123};\n"
            "    int dst[20];\n"
            "    int cnt = unique_sorted(src, 9, dst);\n"
            "    int exp[] = {0,2,3,5,9,123};\n"
            "    assert(cnt == 6);\n"
            "    for (int i = 0; i < 6; i++) assert(dst[i] == exp[i]);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/38",
        "language": "c",
        "entry_point": "max_element",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Return the maximum element in arr of length n.\n"
            "int max_element(int *arr, int n) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    int a[] = {1,5,3,9,2};\n"
            "    assert(max_element(a, 5) == 9);\n"
            "    int b[] = {-1,-5,-3};\n"
            "    assert(max_element(b, 3) == -1);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/39",
        "language": "c",
        "entry_point": "gcd",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <assert.h>\n\n"
            "// Return the greatest common divisor of a and b.\n"
            "int gcd(int a, int b) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(gcd(12, 8) == 4);\n"
            "    assert(gcd(7, 13) == 1);\n"
            "    assert(gcd(100, 25) == 25);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/c/40",
        "language": "c",
        "entry_point": "abs_value",
        "prompt": (
            "// Complete this C function. Return a full compilable C program.\n\n"
            "#include <stdio.h>\n"
            "#include <math.h>\n"
            "#include <assert.h>\n\n"
            "// Return the absolute value of a double.\n"
            "double abs_value(double x) {\n"
            "    // your code here\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(fabs(abs_value(-3.5) - 3.5) < 1e-9);\n"
            "    assert(fabs(abs_value(0.0)) < 1e-9);\n"
            "    assert(fabs(abs_value(5.0) - 5.0) < 1e-9);\n"
            '    printf("PASS\\n");\n'
            "    return 0;\n"
            "}\n"
        ),
        "test": "",
    },
]

_CPP_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/cpp/0",
        "language": "cpp",
        "entry_point": "hasCloseElements",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <cmath>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "bool hasCloseElements(vector<double>& numbers, double threshold) {\n"
            "    // your code here\n"
            "    return false;\n"
            "}\n\n"
            "int main() {\n"
            "    vector<double> a1 = {1.0,2.0,3.0};\n"
            "    assert(!hasCloseElements(a1, 0.5));\n"
            "    vector<double> a2 = {1.0,2.8,3.0,4.0,5.0,2.0};\n"
            "    assert(hasCloseElements(a2, 0.3));\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/2",
        "language": "cpp",
        "entry_point": "truncateNumber",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <cmath>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "double truncateNumber(double number) {\n"
            "    // Return the decimal part of a positive float.\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(fabs(truncateNumber(3.5) - 0.5) < 1e-9);\n"
            "    assert(fabs(truncateNumber(1.33) - 0.33) < 1e-4);\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/3",
        "language": "cpp",
        "entry_point": "belowZero",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "bool belowZero(vector<int>& operations) {\n"
            "    // Return true if running balance ever drops below zero.\n"
            "    return false;\n"
            "}\n\n"
            "int main() {\n"
            "    vector<int> a1 = {1,2,3};\n"
            "    assert(!belowZero(a1));\n"
            "    vector<int> a2 = {1,2,-4,5};\n"
            "    assert(belowZero(a2));\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/5",
        "language": "cpp",
        "entry_point": "intersperse",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "vector<int> intersperse(vector<int>& numbers, int delimiter) {\n"
            "    // Insert delimiter between consecutive elements.\n"
            "    return {};\n"
            "}\n\n"
            "int main() {\n"
            "    vector<int> a = {1,2,3};\n"
            "    vector<int> r = intersperse(a, 4);\n"
            "    vector<int> exp = {1,4,2,4,3};\n"
            "    assert(r == exp);\n"
            "    vector<int> e = {};\n"
            "    assert(intersperse(e, 7).empty());\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/7",
        "language": "cpp",
        "entry_point": "filterBySubstring",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <string>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "vector<string> filterBySubstring(vector<string>& strings, const string& substring) {\n"
            "    // Filter strings containing the given substring.\n"
            "    return {};\n"
            "}\n\n"
            "int main() {\n"
            '    vector<string> a = {"abc","def","abcdef"};\n'
            '    vector<string> r = filterBySubstring(a, "abc");\n'
            "    assert(r.size() == 2);\n"
            '    for (auto& s : r) assert(s.find("abc") != string::npos);\n'
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/8",
        "language": "cpp",
        "entry_point": "sumProduct",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "pair<int,int> sumProduct(vector<int>& numbers) {\n"
            "    // Return {sum, product}. Empty => {0, 1}.\n"
            "    return {0, 1};\n"
            "}\n\n"
            "int main() {\n"
            "    vector<int> a = {1,2,3,4};\n"
            "    auto [s, p] = sumProduct(a);\n"
            "    assert(s == 10 && p == 24);\n"
            "    vector<int> e = {};\n"
            "    auto [s2, p2] = sumProduct(e);\n"
            "    assert(s2 == 0 && p2 == 1);\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/11",
        "language": "cpp",
        "entry_point": "stringXor",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <string>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "string stringXor(const string& a, const string& b) {\n"
            "    // XOR two equal-length binary strings.\n"
            '    return "";\n'
            "}\n\n"
            "int main() {\n"
            '    assert(stringXor("010", "110") == "100");\n'
            '    assert(stringXor("0101", "0000") == "0101");\n'
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/12",
        "language": "cpp",
        "entry_point": "longest",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <string>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "string longest(vector<string>& strings) {\n"
            "    // Return the longest string, empty string if list is empty.\n"
            '    return "";\n'
            "}\n\n"
            "int main() {\n"
            '    vector<string> a = {"a","bb","ccc"};\n'
            '    assert(longest(a) == "ccc");\n'
            "    vector<string> e = {};\n"
            '    assert(longest(e) == "");\n'
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/14",
        "language": "cpp",
        "entry_point": "allPrefixes",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <string>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "vector<string> allPrefixes(const string& s) {\n"
            "    // Return all prefixes from shortest to longest.\n"
            "    return {};\n"
            "}\n\n"
            "int main() {\n"
            '    auto r = allPrefixes("abc");\n'
            '    assert(r.size() == 3 && r[0] == "a" && r[1] == "ab" && r[2] == "abc");\n'
            '    assert(allPrefixes("").empty());\n'
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/15",
        "language": "cpp",
        "entry_point": "stringSequence",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <string>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "string stringSequence(int n) {\n"
            "    // Return '0 1 2 ... n'.\n"
            '    return "";\n'
            "}\n\n"
            "int main() {\n"
            '    assert(stringSequence(0) == "0");\n'
            '    assert(stringSequence(5) == "0 1 2 3 4 5");\n'
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/23",
        "language": "cpp",
        "entry_point": "myStrlen",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <string>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int myStrlen(const string& s) {\n"
            "    // Return the length of the string.\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            '    assert(myStrlen("") == 0);\n'
            '    assert(myStrlen("abc") == 3);\n'
            '    assert(myStrlen("hello world") == 11);\n'
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/26",
        "language": "cpp",
        "entry_point": "largestDivisor",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int largestDivisor(int n) {\n"
            "    // Return the largest divisor of n less than n.\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(largestDivisor(15) == 5);\n"
            "    assert(largestDivisor(27) == 9);\n"
            "    assert(largestDivisor(100) == 50);\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/27",
        "language": "cpp",
        "entry_point": "factorize",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "vector<int> factorize(int n) {\n"
            "    // Return prime factorization as sorted vector.\n"
            "    return {};\n"
            "}\n\n"
            "int main() {\n"
            "    assert((factorize(8) == vector<int>{2,2,2}));\n"
            "    assert((factorize(25) == vector<int>{5,5}));\n"
            "    assert((factorize(70) == vector<int>{2,5,7}));\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/32",
        "language": "cpp",
        "entry_point": "isPrime",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "bool isPrime(int n) {\n"
            "    // Return true if n is prime.\n"
            "    return false;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(!isPrime(6));\n"
            "    assert(isPrime(101));\n"
            "    assert(isPrime(11));\n"
            "    assert(isPrime(2));\n"
            "    assert(isPrime(13441));\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/33",
        "language": "cpp",
        "entry_point": "filterOdd",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "vector<int> filterOdd(vector<int>& xs) {\n"
            "    // Return only the odd numbers.\n"
            "    return {};\n"
            "}\n\n"
            "int main() {\n"
            "    vector<int> a = {1,2,3,4,5,6,7,8,9};\n"
            "    auto r = filterOdd(a);\n"
            "    assert(r.size() == 5);\n"
            "    for (int v : r) assert(v % 2 == 1);\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/35",
        "language": "cpp",
        "entry_point": "fibonacci",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int fibonacci(int n) {\n"
            "    // Return nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1).\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(fibonacci(0) == 0);\n"
            "    assert(fibonacci(1) == 1);\n"
            "    assert(fibonacci(10) == 55);\n"
            "    assert(fibonacci(20) == 6765);\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/36",
        "language": "cpp",
        "entry_point": "reverseString",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <string>\n"
            "#include <algorithm>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "string reverseString(const string& s) {\n"
            "    // Return the reversed string.\n"
            '    return "";\n'
            "}\n\n"
            "int main() {\n"
            '    assert(reverseString("hello") == "olleh");\n'
            '    assert(reverseString("") == "");\n'
            '    assert(reverseString("a") == "a");\n'
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/37",
        "language": "cpp",
        "entry_point": "uniqueSorted",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <algorithm>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "vector<int> uniqueSorted(vector<int>& lst) {\n"
            "    // Return sorted unique values.\n"
            "    return {};\n"
            "}\n\n"
            "int main() {\n"
            "    vector<int> a = {5,3,5,2,3,3,9,0,123};\n"
            "    vector<int> exp = {0,2,3,5,9,123};\n"
            "    assert(uniqueSorted(a) == exp);\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/38",
        "language": "cpp",
        "entry_point": "maxElement",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <vector>\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int maxElement(vector<int>& arr) {\n"
            "    // Return the maximum element.\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    vector<int> a = {1,5,3,9,2};\n"
            "    assert(maxElement(a) == 9);\n"
            "    vector<int> b = {-1,-5,-3};\n"
            "    assert(maxElement(b) == -1);\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/cpp/39",
        "language": "cpp",
        "entry_point": "gcd",
        "prompt": (
            "// Complete this C++ function. Return a full compilable C++ program.\n\n"
            "#include <cassert>\n"
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int gcd(int a, int b) {\n"
            "    // Return the greatest common divisor.\n"
            "    return 0;\n"
            "}\n\n"
            "int main() {\n"
            "    assert(gcd(12, 8) == 4);\n"
            "    assert(gcd(7, 13) == 1);\n"
            "    assert(gcd(100, 25) == 25);\n"
            '    cout << "PASS" << endl;\n'
            "}\n"
        ),
        "test": "",
    },
]

_JAVA_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/java/0",
        "language": "java",
        "entry_point": "hasCloseElements",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Check if any two numbers in the list are closer than threshold.\n"
            "     */\n"
            "    public static boolean hasCloseElements(List<Double> numbers, double threshold) {\n"
            "        // your code here\n"
            "        return false;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (hasCloseElements(Arrays.asList(1.0,2.0,3.0), 0.5)) throw new RuntimeException("fail1");\n'
            '        if (!hasCloseElements(Arrays.asList(1.0,2.8,3.0,4.0,5.0,2.0), 0.3)) throw new RuntimeException("fail2");\n'
            '        if (!hasCloseElements(Arrays.asList(1.0,2.0,3.9,4.0,5.0,2.2), 0.3)) throw new RuntimeException("fail3");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/2",
        "language": "java",
        "entry_point": "truncateNumber",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Return the decimal part of a positive float.\n"
            "     * truncateNumber(3.5) == 0.5\n"
            "     */\n"
            "    public static double truncateNumber(double number) {\n"
            "        // your code here\n"
            "        return 0;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (Math.abs(truncateNumber(3.5) - 0.5) > 1e-9) throw new RuntimeException("fail1");\n'
            '        if (Math.abs(truncateNumber(1.33) - 0.33) > 1e-4) throw new RuntimeException("fail2");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/3",
        "language": "java",
        "entry_point": "belowZero",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Given a list of deposit/withdrawal operations on a zero-balance account,\n"
            "     * return true if the balance ever drops below zero.\n"
            "     */\n"
            "    public static boolean belowZero(List<Integer> operations) {\n"
            "        // your code here\n"
            "        return false;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (belowZero(Arrays.asList(1,2,3))) throw new RuntimeException("fail1");\n'
            '        if (!belowZero(Arrays.asList(1,2,-4,5))) throw new RuntimeException("fail2");\n'
            '        if (belowZero(Arrays.asList(1,-1,2,-2,5,3,-3))) throw new RuntimeException("fail3");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/5",
        "language": "java",
        "entry_point": "intersperse",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Insert delimiter between every pair of consecutive elements.\n"
            "     * intersperse([1,2,3], 4) => [1,4,2,4,3]\n"
            "     */\n"
            "    public static List<Integer> intersperse(List<Integer> numbers, int delimiter) {\n"
            "        // your code here\n"
            "        return new ArrayList<>();\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (!intersperse(Arrays.asList(1,2,3), 4).equals(Arrays.asList(1,4,2,4,3))) throw new RuntimeException("fail1");\n'
            '        if (!intersperse(new ArrayList<>(), 7).isEmpty()) throw new RuntimeException("fail2");\n'
            '        if (!intersperse(Arrays.asList(1), 7).equals(Arrays.asList(1))) throw new RuntimeException("fail3");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/7",
        "language": "java",
        "entry_point": "filterBySubstring",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\nimport java.util.stream.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Filter a list of strings to those containing the given substring.\n"
            "     */\n"
            "    public static List<String> filterBySubstring(List<String> strings, String substring) {\n"
            "        // your code here\n"
            "        return new ArrayList<>();\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        List<String> r = filterBySubstring(Arrays.asList("abc","def","abcdef"), "abc");\n'
            '        if (!r.equals(Arrays.asList("abc","abcdef"))) throw new RuntimeException("fail1");\n'
            '        if (!filterBySubstring(new ArrayList<>(), "x").isEmpty()) throw new RuntimeException("fail2");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/8",
        "language": "java",
        "entry_point": "sumProduct",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Return an int array [sum, product] of all integers in the list.\n"
            "     * For empty list, return [0, 1].\n"
            "     */\n"
            "    public static int[] sumProduct(List<Integer> numbers) {\n"
            "        // your code here\n"
            "        return new int[]{0, 1};\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            "        int[] r = sumProduct(Arrays.asList(1,2,3,4));\n"
            '        if (r[0] != 10 || r[1] != 24) throw new RuntimeException("fail1");\n'
            "        int[] r2 = sumProduct(new ArrayList<>());\n"
            '        if (r2[0] != 0 || r2[1] != 1) throw new RuntimeException("fail2");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/10",
        "language": "java",
        "entry_point": "makePalindrome",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Find the shortest palindrome by appending characters to the end of s.\n"
            '     * makePalindrome("") => ""\n'
            '     * makePalindrome("cat") => "catac"\n'
            '     * makePalindrome("cata") => "catac"\n'
            "     */\n"
            "    public static String makePalindrome(String s) {\n"
            "        // your code here\n"
            '        return "";\n'
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (!makePalindrome("").equals("")) throw new RuntimeException("fail1");\n'
            '        if (!makePalindrome("cat").equals("catac")) throw new RuntimeException("fail2");\n'
            '        if (!makePalindrome("cata").equals("catac")) throw new RuntimeException("fail3");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/11",
        "language": "java",
        "entry_point": "stringXor",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * XOR two binary strings of equal length.\n"
            '     * stringXor("010", "110") => "100"\n'
            "     */\n"
            "    public static String stringXor(String a, String b) {\n"
            "        // your code here\n"
            '        return "";\n'
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (!stringXor("010", "110").equals("100")) throw new RuntimeException("fail1");\n'
            '        if (!stringXor("0101", "0000").equals("0101")) throw new RuntimeException("fail2");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/12",
        "language": "java",
        "entry_point": "longest",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Return the longest string in the list, or null if empty.\n"
            "     * If there are ties, return the first one.\n"
            "     */\n"
            "    public static String longest(List<String> strings) {\n"
            "        // your code here\n"
            "        return null;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (!longest(Arrays.asList("a","bb","ccc")).equals("ccc")) throw new RuntimeException("fail1");\n'
            '        if (longest(new ArrayList<>()) != null) throw new RuntimeException("fail2");\n'
            '        if (!longest(Arrays.asList("a","b","c")).equals("a")) throw new RuntimeException("fail3");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/14",
        "language": "java",
        "entry_point": "allPrefixes",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Return all prefixes of s from shortest to longest.\n"
            '     * allPrefixes("abc") => ["a", "ab", "abc"]\n'
            "     */\n"
            "    public static List<String> allPrefixes(String s) {\n"
            "        // your code here\n"
            "        return new ArrayList<>();\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (!allPrefixes("abc").equals(Arrays.asList("a","ab","abc"))) throw new RuntimeException("fail1");\n'
            '        if (!allPrefixes("").isEmpty()) throw new RuntimeException("fail2");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/15",
        "language": "java",
        "entry_point": "stringSequence",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Return a string of space-separated numbers from 0 to n (inclusive).\n"
            '     * stringSequence(0) => "0"\n'
            '     * stringSequence(5) => "0 1 2 3 4 5"\n'
            "     */\n"
            "    public static String stringSequence(int n) {\n"
            "        // your code here\n"
            '        return "";\n'
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (!stringSequence(0).equals("0")) throw new RuntimeException("fail1");\n'
            '        if (!stringSequence(5).equals("0 1 2 3 4 5")) throw new RuntimeException("fail2");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/17",
        "language": "java",
        "entry_point": "parseMusic",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Parse a music string into beat counts.\n"
            "     * 'o' = 4 beats, 'o|' = 2 beats, '.|' = 1 beat.\n"
            '     * parseMusic("o o| .|") => [4, 2, 1]\n'
            "     */\n"
            "    public static List<Integer> parseMusic(String musicString) {\n"
            "        // your code here\n"
            "        return new ArrayList<>();\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (!parseMusic("o o| .|").equals(Arrays.asList(4,2,1))) throw new RuntimeException("fail1");\n'
            '        if (!parseMusic("").isEmpty()) throw new RuntimeException("fail2");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/19",
        "language": "java",
        "entry_point": "sortNumbers",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Sort a space-separated string of number words ('zero' through 'nine').\n"
            '     * sortNumbers("three one five") => "one three five"\n'
            "     */\n"
            "    public static String sortNumbers(String numbers) {\n"
            "        // your code here\n"
            '        return "";\n'
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (!sortNumbers("three one five").equals("one three five")) throw new RuntimeException("fail1");\n'
            '        if (!sortNumbers("").equals("")) throw new RuntimeException("fail2");\n'
            '        if (!sortNumbers("nine zero").equals("zero nine")) throw new RuntimeException("fail3");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/20",
        "language": "java",
        "entry_point": "findClosestElements",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * From a list of numbers, find the two closest elements.\n"
            "     * Return them as a double[] {smaller, larger}.\n"
            "     */\n"
            "    public static double[] findClosestElements(List<Double> numbers) {\n"
            "        // your code here\n"
            "        return new double[]{0, 0};\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            "        double[] r = findClosestElements(Arrays.asList(1.0,2.0,3.0,4.0,5.0,2.2));\n"
            '        if (Math.abs(r[0]-2.0) > 1e-9 || Math.abs(r[1]-2.2) > 1e-9) throw new RuntimeException("fail1");\n'
            "        double[] r2 = findClosestElements(Arrays.asList(1.0,2.0,3.0,4.0,5.0,2.0));\n"
            '        if (Math.abs(r2[0]-2.0) > 1e-9 || Math.abs(r2[1]-2.0) > 1e-9) throw new RuntimeException("fail2");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/21",
        "language": "java",
        "entry_point": "rescaleToUnit",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\nimport java.util.stream.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Rescale a list so min becomes 0.0 and max becomes 1.0.\n"
            "     */\n"
            "    public static List<Double> rescaleToUnit(List<Double> numbers) {\n"
            "        // your code here\n"
            "        return new ArrayList<>();\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            "        List<Double> r = rescaleToUnit(Arrays.asList(1.0,2.0,3.0,4.0,5.0));\n"
            "        double[] exp = {0.0, 0.25, 0.5, 0.75, 1.0};\n"
            "        for (int i = 0; i < exp.length; i++) {\n"
            '            if (Math.abs(r.get(i) - exp[i]) > 1e-9) throw new RuntimeException("fail at " + i);\n'
            "        }\n"
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/22",
        "language": "java",
        "entry_point": "filterIntegers",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\nimport java.util.stream.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Filter a list of Objects to return only those that are Integers.\n"
            "     */\n"
            "    public static List<Integer> filterIntegers(List<Object> values) {\n"
            "        // your code here\n"
            "        return new ArrayList<>();\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        List<Integer> r = filterIntegers(Arrays.asList("a", 3.14, 5, "b", 6));\n'
            '        if (!r.equals(Arrays.asList(5, 6))) throw new RuntimeException("fail1");\n'
            '        if (!filterIntegers(new ArrayList<>()).isEmpty()) throw new RuntimeException("fail2");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/23",
        "language": "java",
        "entry_point": "strlen",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Return the length of a string.\n"
            "     */\n"
            "    public static int strlen(String s) {\n"
            "        // your code here\n"
            "        return 0;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (strlen("") != 0) throw new RuntimeException("fail1");\n'
            '        if (strlen("abc") != 3) throw new RuntimeException("fail2");\n'
            '        if (strlen("hello world") != 11) throw new RuntimeException("fail3");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/26",
        "language": "java",
        "entry_point": "largestDivisor",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Return the largest divisor of n (not including n itself).\n"
            "     * largestDivisor(15) == 5\n"
            "     */\n"
            "    public static int largestDivisor(int n) {\n"
            "        // your code here\n"
            "        return 1;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (largestDivisor(15) != 5) throw new RuntimeException("fail1");\n'
            '        if (largestDivisor(27) != 9) throw new RuntimeException("fail2");\n'
            '        if (largestDivisor(100) != 50) throw new RuntimeException("fail3");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/27",
        "language": "java",
        "entry_point": "factorize",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "import java.util.*;\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Return the prime factorization of n as a sorted list.\n"
            "     * factorize(8) => [2, 2, 2]\n"
            "     * factorize(25) => [5, 5]\n"
            "     * factorize(70) => [2, 5, 7]\n"
            "     */\n"
            "    public static List<Integer> factorize(int n) {\n"
            "        // your code here\n"
            "        return new ArrayList<>();\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (!factorize(8).equals(Arrays.asList(2,2,2))) throw new RuntimeException("fail1");\n'
            '        if (!factorize(25).equals(Arrays.asList(5,5))) throw new RuntimeException("fail2");\n'
            '        if (!factorize(70).equals(Arrays.asList(2,5,7))) throw new RuntimeException("fail3");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
    {
        "task_id": "MultiPL-E/java/32",
        "language": "java",
        "entry_point": "isPrime",
        "prompt": (
            "// Complete this Java program. Return ONLY compilable Java code.\n\n"
            "public class Solution {\n"
            "    /**\n"
            "     * Return true if n is a prime number.\n"
            "     * isPrime(6) == false, isPrime(101) == true, isPrime(2) == true\n"
            "     */\n"
            "    public static boolean isPrime(int n) {\n"
            "        // your code here\n"
            "        return false;\n"
            "    }\n\n"
            "    public static void main(String[] args) {\n"
            '        if (isPrime(6)) throw new RuntimeException("fail1");\n'
            '        if (!isPrime(101)) throw new RuntimeException("fail2");\n'
            '        if (!isPrime(11)) throw new RuntimeException("fail3");\n'
            '        if (!isPrime(13441)) throw new RuntimeException("fail4");\n'
            '        if (!isPrime(2)) throw new RuntimeException("fail5");\n'
            '        System.out.println("PASS");\n'
            "    }\n"
            "}\n"
        ),
        "test": "",
    },
]

# ── Ruby Problems ─────────────────────────────────────────────────────────────
_RUBY_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/ruby/0",
        "language": "ruby",
        "entry_point": "has_close_elements",
        "prompt": (
            "# Complete this Ruby function.\n"
            "# Return ONLY the complete function — no markdown, no explanation.\n\n"
            "# Check if any two numbers in the array are closer than threshold.\n"
            "# @param numbers [Array<Float>]\n"
            "# @param threshold [Float]\n"
            "# @return [Boolean]\n"
            "def has_close_elements(numbers, threshold)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless has_close_elements([1.0, 2.0, 3.0], 0.5) == false\n"
            "raise 'fail 2' unless has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3) == true\n"
            "raise 'fail 3' unless has_close_elements([1.0, 2.0, 3.9, 4.0, 5.0], 0.3) == true\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def has_close_elements(numbers, threshold)\n"
            "  numbers.combination(2).any? { |a, b| (a - b).abs < threshold }\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ruby/1",
        "language": "ruby",
        "entry_point": "below_zero",
        "prompt": (
            "# Complete this Ruby function.\n\n"
            "# Given deposit/withdrawal ops on a zero-balance account,\n"
            "# return true if balance ever goes below zero.\n"
            "# @param operations [Array<Integer>]\n"
            "# @return [Boolean]\n"
            "def below_zero(operations)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless below_zero([1, 2, 3]) == false\n"
            "raise 'fail 2' unless below_zero([1, 2, -4, 5]) == true\n"
            "raise 'fail 3' unless below_zero([1, -1, 2, -2, 5]) == false\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def below_zero(operations)\n"
            "  balance = 0\n"
            "  operations.each { |op| balance += op; return true if balance < 0 }\n"
            "  false\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ruby/2",
        "language": "ruby",
        "entry_point": "mean_absolute_deviation",
        "prompt": (
            "# Complete this Ruby function.\n\n"
            "# Return mean absolute deviation of an array of numbers.\n"
            "# @param numbers [Array<Float>]\n"
            "# @return [Float]\n"
            "def mean_absolute_deviation(numbers)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless (mean_absolute_deviation([1.0, 2.0, 3.0]) - 0.6666666666666667).abs < 1e-6\n"
            "raise 'fail 2' unless (mean_absolute_deviation([1.0, 2.0, 3.0, 4.0]) - 1.0).abs < 1e-6\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def mean_absolute_deviation(numbers)\n"
            "  mean = numbers.sum.to_f / numbers.length\n"
            "  numbers.sum { |n| (n - mean).abs } / numbers.length\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ruby/3",
        "language": "ruby",
        "entry_point": "intersperse",
        "prompt": (
            "# Complete this Ruby function.\n\n"
            "# Insert delimiter between every two consecutive elements.\n"
            "# intersperse([1,2,3], 4) => [1,4,2,4,3]\n"
            "# @param numbers [Array<Integer>]\n"
            "# @param delimiter [Integer]\n"
            "# @return [Array<Integer>]\n"
            "def intersperse(numbers, delimiter)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless intersperse([], 4) == []\n"
            "raise 'fail 2' unless intersperse([1, 2, 3], 4) == [1, 4, 2, 4, 3]\n"
            "raise 'fail 3' unless intersperse([1, 2, 3, 4], 5) == [1, 5, 2, 5, 3, 5, 4]\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def intersperse(numbers, delimiter)\n"
            "  return [] if numbers.empty?\n"
            "  result = []\n"
            "  numbers.each_with_index { |n, i| result << n; result << delimiter unless i == numbers.length - 1 }\n"
            "  result\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ruby/4",
        "language": "ruby",
        "entry_point": "sum_product",
        "prompt": (
            "# Complete this Ruby function.\n\n"
            "# Return array [sum, product] of integers.\n"
            "# sum_product([]) => [0, 1]\n"
            "# @param numbers [Array<Integer>]\n"
            "# @return [Array<Integer>]\n"
            "def sum_product(numbers)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless sum_product([]) == [0, 1]\n"
            "raise 'fail 2' unless sum_product([1, 2, 3, 4]) == [10, 24]\n"
            "raise 'fail 3' unless sum_product([1, 1, 1]) == [3, 1]\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def sum_product(numbers)\n"
            "  [numbers.sum, numbers.reduce(1, :*)]\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ruby/5",
        "language": "ruby",
        "entry_point": "even_odd_count",
        "prompt": (
            "# Complete this Ruby function.\n\n"
            "# Return [count_even_digits, count_odd_digits] for a number.\n"
            "# even_odd_count(1234) => [2, 2]\n"
            "# @param num [Integer]\n"
            "# @return [Array<Integer>]\n"
            "def even_odd_count(num)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless even_odd_count(1234) == [2, 2]\n"
            "raise 'fail 2' unless even_odd_count(-12) == [1, 1]\n"
            "raise 'fail 3' unless even_odd_count(0) == [1, 0]\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def even_odd_count(num)\n"
            "  digits = num.abs.to_s.chars.map(&:to_i)\n"
            "  [digits.count(&:even?), digits.count(&:odd?)]\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ruby/6",
        "language": "ruby",
        "entry_point": "is_palindrome",
        "prompt": (
            "# Complete this Ruby function.\n\n"
            "# Return true if the string is a palindrome.\n"
            "# @param s [String]\n"
            "# @return [Boolean]\n"
            "def is_palindrome(s)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless is_palindrome('') == true\n"
            "raise 'fail 2' unless is_palindrome('aba') == true\n"
            "raise 'fail 3' unless is_palindrome('abba') == true\n"
            "raise 'fail 4' unless is_palindrome('abc') == false\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def is_palindrome(s)\n"
            "  s == s.reverse\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ruby/7",
        "language": "ruby",
        "entry_point": "count_vowels",
        "prompt": (
            "# Complete this Ruby function.\n\n"
            "# Return the number of vowels (aeiouAEIOU) in the string.\n"
            "# @param s [String]\n"
            "# @return [Integer]\n"
            "def count_vowels(s)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless count_vowels('') == 0\n"
            "raise 'fail 2' unless count_vowels('hello') == 2\n"
            "raise 'fail 3' unless count_vowels('AEIOU') == 5\n"
            "raise 'fail 4' unless count_vowels('xyz') == 0\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def count_vowels(s)\n"
            "  s.count('aeiouAEIOU')\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ruby/8",
        "language": "ruby",
        "entry_point": "flatten_array",
        "prompt": (
            "# Complete this Ruby function.\n\n"
            "# Flatten a nested array one level deep.\n"
            "# flatten_array([[1,2],[3,4],[5]]) => [1,2,3,4,5]\n"
            "# @param arr [Array]\n"
            "# @return [Array]\n"
            "def flatten_array(arr)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless flatten_array([]) == []\n"
            "raise 'fail 2' unless flatten_array([[1, 2], [3, 4]]) == [1, 2, 3, 4]\n"
            "raise 'fail 3' unless flatten_array([[1], [2], [3]]) == [1, 2, 3]\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def flatten_array(arr)\n"
            "  arr.flatten(1)\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/ruby/9",
        "language": "ruby",
        "entry_point": "fibonacci",
        "prompt": (
            "# Complete this Ruby function.\n\n"
            "# Return the nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1).\n"
            "# @param n [Integer]\n"
            "# @return [Integer]\n"
            "def fibonacci(n)\n"
            "  # your code here\n"
            "end\n"
        ),
        "test": (
            "raise 'fail 1' unless fibonacci(0) == 0\n"
            "raise 'fail 2' unless fibonacci(1) == 1\n"
            "raise 'fail 3' unless fibonacci(5) == 5\n"
            "raise 'fail 4' unless fibonacci(10) == 55\n"
            "puts 'ok'\n"
        ),
        "canonical_solution": (
            "def fibonacci(n)\n"
            "  return n if n <= 1\n"
            "  a, b = 0, 1\n"
            "  (n - 1).times { a, b = b, a + b }\n"
            "  b\n"
            "end\n"
        ),
    },
]


# ── PHP Problems ──────────────────────────────────────────────────────────────
_PHP_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/php/0",
        "language": "php",
        "entry_point": "has_close_elements",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n"
            "// Return ONLY the complete runnable PHP code — no markdown, no explanation.\n\n"
            "/**\n"
            " * Check if any two numbers in the array are closer than threshold.\n"
            " * @param float[] $numbers\n"
            " * @param float $threshold\n"
            " * @return bool\n"
            " */\n"
            "function has_close_elements(array $numbers, float $threshold): bool {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (has_close_elements([1.0, 2.0, 3.0], 0.5) !== false) { exit(1); }\n"
            "if (has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3) !== true) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function has_close_elements(array $numbers, float $threshold): bool {\n"
            "    $n = count($numbers);\n"
            "    for ($i = 0; $i < $n; $i++) {\n"
            "        for ($j = $i + 1; $j < $n; $j++) {\n"
            "            if (abs($numbers[$i] - $numbers[$j]) < $threshold) return true;\n"
            "        }\n"
            "    }\n"
            "    return false;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/php/1",
        "language": "php",
        "entry_point": "below_zero",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n\n"
            "/**\n"
            " * Return true if balance ever goes below zero.\n"
            " * @param int[] $operations\n"
            " * @return bool\n"
            " */\n"
            "function below_zero(array $operations): bool {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (below_zero([1, 2, 3]) !== false) { exit(1); }\n"
            "if (below_zero([1, 2, -4, 5]) !== true) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function below_zero(array $operations): bool {\n"
            "    $balance = 0;\n"
            "    foreach ($operations as $op) {\n"
            "        $balance += $op;\n"
            "        if ($balance < 0) return true;\n"
            "    }\n"
            "    return false;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/php/2",
        "language": "php",
        "entry_point": "mean_absolute_deviation",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n\n"
            "/**\n"
            " * Return mean absolute deviation of an array.\n"
            " * @param float[] $numbers\n"
            " * @return float\n"
            " */\n"
            "function mean_absolute_deviation(array $numbers): float {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (abs(mean_absolute_deviation([1.0, 2.0, 3.0]) - 0.6666666666666667) > 1e-6) { exit(1); }\n"
            "if (abs(mean_absolute_deviation([1.0, 2.0, 3.0, 4.0]) - 1.0) > 1e-6) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function mean_absolute_deviation(array $numbers): float {\n"
            "    $n = count($numbers);\n"
            "    $mean = array_sum($numbers) / $n;\n"
            "    return array_sum(array_map(fn($x) => abs($x - $mean), $numbers)) / $n;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/php/3",
        "language": "php",
        "entry_point": "intersperse",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n\n"
            "/**\n"
            " * Insert delimiter between every two consecutive elements.\n"
            " * @param int[] $numbers\n"
            " * @param int $delimiter\n"
            " * @return int[]\n"
            " */\n"
            "function intersperse(array $numbers, int $delimiter): array {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (intersperse([], 4) !== []) { exit(1); }\n"
            "if (intersperse([1, 2, 3], 4) !== [1, 4, 2, 4, 3]) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function intersperse(array $numbers, int $delimiter): array {\n"
            "    if (empty($numbers)) return [];\n"
            "    $result = [];\n"
            "    foreach ($numbers as $i => $n) {\n"
            "        $result[] = $n;\n"
            "        if ($i < count($numbers) - 1) $result[] = $delimiter;\n"
            "    }\n"
            "    return array_values($result);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/php/4",
        "language": "php",
        "entry_point": "is_palindrome",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n\n"
            "/**\n"
            " * Return true if the string is a palindrome.\n"
            " * @param string $s\n"
            " * @return bool\n"
            " */\n"
            "function is_palindrome(string $s): bool {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (is_palindrome('') !== true) { exit(1); }\n"
            "if (is_palindrome('aba') !== true) { exit(1); }\n"
            "if (is_palindrome('abc') !== false) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function is_palindrome(string $s): bool {\n"
            "    return $s === strrev($s);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/php/5",
        "language": "php",
        "entry_point": "fibonacci",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n\n"
            "/**\n"
            " * Return the nth Fibonacci number (0-indexed).\n"
            " * @param int $n\n"
            " * @return int\n"
            " */\n"
            "function fibonacci(int $n): int {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (fibonacci(0) !== 0) { exit(1); }\n"
            "if (fibonacci(1) !== 1) { exit(1); }\n"
            "if (fibonacci(5) !== 5) { exit(1); }\n"
            "if (fibonacci(10) !== 55) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function fibonacci(int $n): int {\n"
            "    if ($n <= 1) return $n;\n"
            "    $a = 0; $b = 1;\n"
            "    for ($i = 2; $i <= $n; $i++) { [$a, $b] = [$b, $a + $b]; }\n"
            "    return $b;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/php/6",
        "language": "php",
        "entry_point": "count_vowels",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n\n"
            "/**\n"
            " * Return number of vowels (aeiouAEIOU) in string.\n"
            " * @param string $s\n"
            " * @return int\n"
            " */\n"
            "function count_vowels(string $s): int {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (count_vowels('') !== 0) { exit(1); }\n"
            "if (count_vowels('hello') !== 2) { exit(1); }\n"
            "if (count_vowels('AEIOU') !== 5) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function count_vowels(string $s): int {\n"
            "    return preg_match_all('/[aeiouAEIOU]/', $s);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/php/7",
        "language": "php",
        "entry_point": "sum_product",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n\n"
            "/**\n"
            " * Return [sum, product] of integers. sum_product([]) => [0, 1]\n"
            " * @param int[] $numbers\n"
            " * @return int[]\n"
            " */\n"
            "function sum_product(array $numbers): array {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (sum_product([]) !== [0, 1]) { exit(1); }\n"
            "if (sum_product([1, 2, 3, 4]) !== [10, 24]) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function sum_product(array $numbers): array {\n"
            "    return [array_sum($numbers), empty($numbers) ? 1 : array_product($numbers)];\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/php/8",
        "language": "php",
        "entry_point": "truncate_number",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n\n"
            "/**\n"
            " * Return the decimal part of a positive float.\n"
            " * truncate_number(3.5) === 0.5\n"
            " * @param float $n\n"
            " * @return float\n"
            " */\n"
            "function truncate_number(float $n): float {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (abs(truncate_number(3.5) - 0.5) > 1e-9) { exit(1); }\n"
            "if (abs(truncate_number(1.33) - 0.33) > 1e-4) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function truncate_number(float $n): float {\n"
            "    return $n - floor($n);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/php/9",
        "language": "php",
        "entry_point": "sort_array",
        "prompt": (
            "<?php\n"
            "// Complete this PHP function.\n\n"
            "/**\n"
            " * Sort array in ascending order without modifying original.\n"
            " * @param int[] $arr\n"
            " * @return int[]\n"
            " */\n"
            "function sort_array(array $arr): array {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "if (sort_array([3, 1, 2]) !== [1, 2, 3]) { exit(1); }\n"
            "if (sort_array([]) !== []) { exit(1); }\n"
            "if (sort_array([1]) !== [1]) { exit(1); }\n"
            "echo 'ok';\n"
        ),
        "canonical_solution": (
            "function sort_array(array $arr): array {\n"
            "    sort($arr);\n"
            "    return $arr;\n"
            "}\n"
        ),
    },
]


# ── Lua Problems ──────────────────────────────────────────────────────────────
_LUA_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/lua/0",
        "language": "lua",
        "entry_point": "has_close_elements",
        "prompt": (
            "-- Complete this Lua function.\n"
            "-- Return ONLY the complete function — no markdown, no explanation.\n\n"
            "-- Check if any two numbers in the table are closer than threshold.\n"
            "function has_close_elements(numbers, threshold)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "assert(has_close_elements({1.0, 2.0, 3.0}, 0.5) == false, 'fail 1')\n"
            "assert(has_close_elements({1.0, 2.8, 3.0, 4.0}, 0.3) == true, 'fail 2')\n"
            "assert(has_close_elements({1.0, 2.0, 3.9, 4.0}, 0.3) == true, 'fail 3')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function has_close_elements(numbers, threshold)\n"
            "  for i = 1, #numbers do\n"
            "    for j = i + 1, #numbers do\n"
            "      if math.abs(numbers[i] - numbers[j]) < threshold then return true end\n"
            "    end\n"
            "  end\n"
            "  return false\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/lua/1",
        "language": "lua",
        "entry_point": "below_zero",
        "prompt": (
            "-- Complete this Lua function.\n\n"
            "-- Return true if balance ever goes below zero.\n"
            "function below_zero(operations)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "assert(below_zero({1, 2, 3}) == false, 'fail 1')\n"
            "assert(below_zero({1, 2, -4, 5}) == true, 'fail 2')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function below_zero(operations)\n"
            "  local balance = 0\n"
            "  for _, op in ipairs(operations) do\n"
            "    balance = balance + op\n"
            "    if balance < 0 then return true end\n"
            "  end\n"
            "  return false\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/lua/2",
        "language": "lua",
        "entry_point": "is_palindrome",
        "prompt": (
            "-- Complete this Lua function.\n\n"
            "-- Return true if the string is a palindrome.\n"
            "function is_palindrome(s)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "assert(is_palindrome('') == true, 'fail 1')\n"
            "assert(is_palindrome('aba') == true, 'fail 2')\n"
            "assert(is_palindrome('abc') == false, 'fail 3')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function is_palindrome(s)\n"
            "  return s == s:reverse()\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/lua/3",
        "language": "lua",
        "entry_point": "sum_array",
        "prompt": (
            "-- Complete this Lua function.\n\n"
            "-- Return the sum of all elements in a table of numbers.\n"
            "function sum_array(arr)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "assert(sum_array({}) == 0, 'fail 1')\n"
            "assert(sum_array({1, 2, 3, 4}) == 10, 'fail 2')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function sum_array(arr)\n"
            "  local s = 0\n"
            "  for _, v in ipairs(arr) do s = s + v end\n"
            "  return s\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/lua/4",
        "language": "lua",
        "entry_point": "fibonacci",
        "prompt": (
            "-- Complete this Lua function.\n\n"
            "-- Return the nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1).\n"
            "function fibonacci(n)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "assert(fibonacci(0) == 0, 'fail 1')\n"
            "assert(fibonacci(1) == 1, 'fail 2')\n"
            "assert(fibonacci(5) == 5, 'fail 3')\n"
            "assert(fibonacci(10) == 55, 'fail 4')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function fibonacci(n)\n"
            "  if n <= 1 then return n end\n"
            "  local a, b = 0, 1\n"
            "  for i = 2, n do a, b = b, a + b end\n"
            "  return b\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/lua/5",
        "language": "lua",
        "entry_point": "count_vowels",
        "prompt": (
            "-- Complete this Lua function.\n\n"
            "-- Return the number of vowels (aeiouAEIOU) in the string.\n"
            "function count_vowels(s)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "assert(count_vowels('') == 0, 'fail 1')\n"
            "assert(count_vowels('hello') == 2, 'fail 2')\n"
            "assert(count_vowels('AEIOU') == 5, 'fail 3')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function count_vowels(s)\n"
            "  local count = 0\n"
            "  for c in s:gmatch('.') do\n"
            "    if c:match('[aeiouAEIOU]') then count = count + 1 end\n"
            "  end\n"
            "  return count\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/lua/6",
        "language": "lua",
        "entry_point": "max_element",
        "prompt": (
            "-- Complete this Lua function.\n\n"
            "-- Return the largest element in a non-empty table of numbers.\n"
            "function max_element(arr)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "assert(max_element({1}) == 1, 'fail 1')\n"
            "assert(max_element({3, 1, 4, 1, 5, 9}) == 9, 'fail 2')\n"
            "assert(max_element({-1, -5, -2}) == -1, 'fail 3')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function max_element(arr)\n"
            "  local m = arr[1]\n"
            "  for _, v in ipairs(arr) do if v > m then m = v end end\n"
            "  return m\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/lua/7",
        "language": "lua",
        "entry_point": "truncate_number",
        "prompt": (
            "-- Complete this Lua function.\n\n"
            "-- Return the decimal part of a positive float.\n"
            "-- truncate_number(3.5) == 0.5\n"
            "function truncate_number(n)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "assert(math.abs(truncate_number(3.5) - 0.5) < 1e-9, 'fail 1')\n"
            "assert(math.abs(truncate_number(1.33) - 0.33) < 1e-4, 'fail 2')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function truncate_number(n)\n"
            "  return n - math.floor(n)\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/lua/8",
        "language": "lua",
        "entry_point": "intersperse",
        "prompt": (
            "-- Complete this Lua function.\n\n"
            "-- Insert delimiter between every two consecutive elements.\n"
            "-- intersperse({1,2,3}, 4) => {1,4,2,4,3}\n"
            "function intersperse(numbers, delimiter)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "local r1 = intersperse({}, 4)\n"
            "assert(#r1 == 0, 'fail 1')\n"
            "local r2 = intersperse({1, 2, 3}, 4)\n"
            "assert(r2[1]==1 and r2[2]==4 and r2[3]==2 and r2[4]==4 and r2[5]==3, 'fail 2')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function intersperse(numbers, delimiter)\n"
            "  if #numbers == 0 then return {} end\n"
            "  local result = {}\n"
            "  for i, v in ipairs(numbers) do\n"
            "    result[#result + 1] = v\n"
            "    if i < #numbers then result[#result + 1] = delimiter end\n"
            "  end\n"
            "  return result\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/lua/9",
        "language": "lua",
        "entry_point": "mean_absolute_deviation",
        "prompt": (
            "-- Complete this Lua function.\n\n"
            "-- Return mean absolute deviation of a table of numbers.\n"
            "function mean_absolute_deviation(numbers)\n"
            "  -- your code here\n"
            "end\n"
        ),
        "test": (
            "assert(math.abs(mean_absolute_deviation({1,2,3}) - 0.6666666666666667) < 1e-6, 'fail 1')\n"
            "assert(math.abs(mean_absolute_deviation({1,2,3,4}) - 1.0) < 1e-6, 'fail 2')\n"
            "print('ok')\n"
        ),
        "canonical_solution": (
            "function mean_absolute_deviation(numbers)\n"
            "  local n = #numbers\n"
            "  local mean = 0\n"
            "  for _, v in ipairs(numbers) do mean = mean + v end\n"
            "  mean = mean / n\n"
            "  local mad = 0\n"
            "  for _, v in ipairs(numbers) do mad = mad + math.abs(v - mean) end\n"
            "  return mad / n\n"
            "end\n"
        ),
    },
]


# ── R Problems ────────────────────────────────────────────────────────────────
_R_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/r/0",
        "language": "r",
        "entry_point": "has_close_elements",
        "prompt": (
            "# Complete this R function.\n"
            "# Return ONLY the complete function — no markdown, no explanation.\n\n"
            "# Check if any two numbers in the vector are closer than threshold.\n"
            "has_close_elements <- function(numbers, threshold) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(has_close_elements(c(1.0, 2.0, 3.0), 0.5) == FALSE)\n"
            "stopifnot(has_close_elements(c(1.0, 2.8, 3.0, 4.0), 0.3) == TRUE)\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "has_close_elements <- function(numbers, threshold) {\n"
            "  n <- length(numbers)\n"
            "  if (n < 2) return(FALSE)\n"
            "  for (i in 1:(n-1)) for (j in (i+1):n)\n"
            "    if (abs(numbers[i] - numbers[j]) < threshold) return(TRUE)\n"
            "  FALSE\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/r/1",
        "language": "r",
        "entry_point": "below_zero",
        "prompt": (
            "# Complete this R function.\n\n"
            "# Return TRUE if balance ever goes below zero.\n"
            "below_zero <- function(operations) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(below_zero(c(1, 2, 3)) == FALSE)\n"
            "stopifnot(below_zero(c(1, 2, -4, 5)) == TRUE)\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "below_zero <- function(operations) {\n"
            "  balance <- 0\n"
            "  for (op in operations) {\n"
            "    balance <- balance + op\n"
            "    if (balance < 0) return(TRUE)\n"
            "  }\n"
            "  FALSE\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/r/2",
        "language": "r",
        "entry_point": "mean_absolute_deviation",
        "prompt": (
            "# Complete this R function.\n\n"
            "# Return mean absolute deviation of a numeric vector.\n"
            "mean_absolute_deviation <- function(numbers) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(abs(mean_absolute_deviation(c(1, 2, 3)) - 2/3) < 1e-6)\n"
            "stopifnot(abs(mean_absolute_deviation(c(1, 2, 3, 4)) - 1.0) < 1e-6)\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "mean_absolute_deviation <- function(numbers) {\n"
            "  mean(abs(numbers - mean(numbers)))\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/r/3",
        "language": "r",
        "entry_point": "fibonacci",
        "prompt": (
            "# Complete this R function.\n\n"
            "# Return the nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1).\n"
            "fibonacci <- function(n) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(fibonacci(0) == 0)\n"
            "stopifnot(fibonacci(1) == 1)\n"
            "stopifnot(fibonacci(5) == 5)\n"
            "stopifnot(fibonacci(10) == 55)\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "fibonacci <- function(n) {\n"
            "  if (n <= 1) return(n)\n"
            "  a <- 0; b <- 1\n"
            "  for (i in 2:n) { temp <- b; b <- a + b; a <- temp }\n"
            "  b\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/r/4",
        "language": "r",
        "entry_point": "is_palindrome",
        "prompt": (
            "# Complete this R function.\n\n"
            "# Return TRUE if the string is a palindrome.\n"
            "is_palindrome <- function(s) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(is_palindrome('') == TRUE)\n"
            "stopifnot(is_palindrome('aba') == TRUE)\n"
            "stopifnot(is_palindrome('abc') == FALSE)\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "is_palindrome <- function(s) {\n"
            "  s == paste(rev(strsplit(s, '')[[1]]), collapse='')\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/r/5",
        "language": "r",
        "entry_point": "sum_product",
        "prompt": (
            "# Complete this R function.\n\n"
            "# Return c(sum, product) of a numeric vector. sum_product(c()) => c(0, 1)\n"
            "sum_product <- function(numbers) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(all(sum_product(c()) == c(0, 1)))\n"
            "stopifnot(all(sum_product(c(1, 2, 3, 4)) == c(10, 24)))\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "sum_product <- function(numbers) {\n"
            "  c(sum(numbers), prod(numbers))\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/r/6",
        "language": "r",
        "entry_point": "count_vowels",
        "prompt": (
            "# Complete this R function.\n\n"
            "# Return the number of vowels (aeiouAEIOU) in the string.\n"
            "count_vowels <- function(s) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(count_vowels('') == 0)\n"
            "stopifnot(count_vowels('hello') == 2)\n"
            "stopifnot(count_vowels('AEIOU') == 5)\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "count_vowels <- function(s) {\n"
            "  nchar(gsub('[^aeiouAEIOU]', '', s))\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/r/7",
        "language": "r",
        "entry_point": "intersperse",
        "prompt": (
            "# Complete this R function.\n\n"
            "# Insert delimiter between every two consecutive elements.\n"
            "# intersperse(c(1,2,3), 4) => c(1,4,2,4,3)\n"
            "intersperse <- function(numbers, delimiter) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(length(intersperse(c(), 4)) == 0)\n"
            "stopifnot(all(intersperse(c(1, 2, 3), 4) == c(1, 4, 2, 4, 3)))\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "intersperse <- function(numbers, delimiter) {\n"
            "  if (length(numbers) == 0) return(c())\n"
            "  result <- c()\n"
            "  for (i in seq_along(numbers)) {\n"
            "    result <- c(result, numbers[i])\n"
            "    if (i < length(numbers)) result <- c(result, delimiter)\n"
            "  }\n"
            "  result\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/r/8",
        "language": "r",
        "entry_point": "max_element",
        "prompt": (
            "# Complete this R function.\n\n"
            "# Return the largest element in a non-empty numeric vector.\n"
            "max_element <- function(arr) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(max_element(c(3, 1, 4, 1, 5, 9)) == 9)\n"
            "stopifnot(max_element(c(-1, -5, -2)) == -1)\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "max_element <- function(arr) {\n"
            "  max(arr)\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/r/9",
        "language": "r",
        "entry_point": "truncate_number",
        "prompt": (
            "# Complete this R function.\n\n"
            "# Return the decimal part of a positive float.\n"
            "# truncate_number(3.5) == 0.5\n"
            "truncate_number <- function(n) {\n"
            "  # your code here\n"
            "}\n"
        ),
        "test": (
            "stopifnot(abs(truncate_number(3.5) - 0.5) < 1e-9)\n"
            "stopifnot(abs(truncate_number(1.33) - 0.33) < 1e-4)\n"
            "cat('ok\\n')\n"
        ),
        "canonical_solution": (
            "truncate_number <- function(n) {\n"
            "  n - floor(n)\n"
            "}\n"
        ),
    },
]


# ── Rust Problems ─────────────────────────────────────────────────────────────
_RUST_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/rust/0",
        "language": "rust",
        "entry_point": "has_close_elements",
        "prompt": (
            "// Complete this Rust function.\n"
            "// Return ONLY the complete runnable Rust program — no markdown.\n\n"
            "fn has_close_elements(numbers: &[f64], threshold: f64) -> bool {\n"
            "    // your code here\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert_eq!(has_close_elements(&[1.0, 2.0, 3.0], 0.5), false);\n"
            "    assert_eq!(has_close_elements(&[1.0, 2.8, 3.0, 4.0], 0.3), true);\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn has_close_elements(numbers: &[f64], threshold: f64) -> bool {\n"
            "    for i in 0..numbers.len() {\n"
            "        for j in (i+1)..numbers.len() {\n"
            "            if (numbers[i] - numbers[j]).abs() < threshold { return true; }\n"
            "        }\n"
            "    }\n"
            "    false\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/rust/1",
        "language": "rust",
        "entry_point": "below_zero",
        "prompt": (
            "// Complete this Rust function.\n\n"
            "fn below_zero(operations: &[i64]) -> bool {\n"
            "    // your code here\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert_eq!(below_zero(&[1, 2, 3]), false);\n"
            "    assert_eq!(below_zero(&[1, 2, -4, 5]), true);\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn below_zero(operations: &[i64]) -> bool {\n"
            "    let mut balance = 0i64;\n"
            "    for &op in operations { balance += op; if balance < 0 { return true; } }\n"
            "    false\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/rust/2",
        "language": "rust",
        "entry_point": "is_palindrome",
        "prompt": (
            "// Complete this Rust function.\n\n"
            "fn is_palindrome(s: &str) -> bool {\n"
            "    // your code here\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert_eq!(is_palindrome(\"\"), true);\n"
            "    assert_eq!(is_palindrome(\"aba\"), true);\n"
            "    assert_eq!(is_palindrome(\"abc\"), false);\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn is_palindrome(s: &str) -> bool {\n"
            "    let chars: Vec<char> = s.chars().collect();\n"
            "    chars == chars.iter().rev().cloned().collect::<Vec<_>>()\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/rust/3",
        "language": "rust",
        "entry_point": "fibonacci",
        "prompt": (
            "// Complete this Rust function.\n\n"
            "fn fibonacci(n: u64) -> u64 {\n"
            "    // your code here\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert_eq!(fibonacci(0), 0);\n"
            "    assert_eq!(fibonacci(1), 1);\n"
            "    assert_eq!(fibonacci(5), 5);\n"
            "    assert_eq!(fibonacci(10), 55);\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn fibonacci(n: u64) -> u64 {\n"
            "    if n <= 1 { return n; }\n"
            "    let (mut a, mut b) = (0u64, 1u64);\n"
            "    for _ in 2..=n { let t = b; b = a + b; a = t; }\n"
            "    b\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/rust/4",
        "language": "rust",
        "entry_point": "sum_product",
        "prompt": (
            "// Complete this Rust function.\n\n"
            "fn sum_product(numbers: &[i64]) -> (i64, i64) {\n"
            "    // your code here — return (sum, product)\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert_eq!(sum_product(&[]), (0, 1));\n"
            "    assert_eq!(sum_product(&[1, 2, 3, 4]), (10, 24));\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn sum_product(numbers: &[i64]) -> (i64, i64) {\n"
            "    (numbers.iter().sum(), numbers.iter().product())\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/rust/5",
        "language": "rust",
        "entry_point": "count_vowels",
        "prompt": (
            "// Complete this Rust function.\n\n"
            "fn count_vowels(s: &str) -> usize {\n"
            "    // your code here\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert_eq!(count_vowels(\"\"), 0);\n"
            "    assert_eq!(count_vowels(\"hello\"), 2);\n"
            "    assert_eq!(count_vowels(\"AEIOU\"), 5);\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn count_vowels(s: &str) -> usize {\n"
            "    s.chars().filter(|c| \"aeiouAEIOU\".contains(*c)).count()\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/rust/6",
        "language": "rust",
        "entry_point": "intersperse",
        "prompt": (
            "// Complete this Rust function.\n\n"
            "fn intersperse(numbers: &[i64], delimiter: i64) -> Vec<i64> {\n"
            "    // your code here\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert_eq!(intersperse(&[], 4), vec![]);\n"
            "    assert_eq!(intersperse(&[1, 2, 3], 4), vec![1, 4, 2, 4, 3]);\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn intersperse(numbers: &[i64], delimiter: i64) -> Vec<i64> {\n"
            "    if numbers.is_empty() { return vec![]; }\n"
            "    let mut result = vec![];\n"
            "    for (i, &n) in numbers.iter().enumerate() {\n"
            "        result.push(n);\n"
            "        if i + 1 < numbers.len() { result.push(delimiter); }\n"
            "    }\n"
            "    result\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/rust/7",
        "language": "rust",
        "entry_point": "max_element",
        "prompt": (
            "// Complete this Rust function.\n\n"
            "fn max_element(arr: &[i64]) -> i64 {\n"
            "    // your code here — arr is guaranteed non-empty\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert_eq!(max_element(&[3, 1, 4, 1, 5, 9]), 9);\n"
            "    assert_eq!(max_element(&[-1, -5, -2]), -1);\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn max_element(arr: &[i64]) -> i64 {\n"
            "    *arr.iter().max().unwrap()\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/rust/8",
        "language": "rust",
        "entry_point": "mean_absolute_deviation",
        "prompt": (
            "// Complete this Rust function.\n\n"
            "fn mean_absolute_deviation(numbers: &[f64]) -> f64 {\n"
            "    // your code here\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert!((mean_absolute_deviation(&[1.0, 2.0, 3.0]) - 2.0/3.0).abs() < 1e-6);\n"
            "    assert!((mean_absolute_deviation(&[1.0, 2.0, 3.0, 4.0]) - 1.0).abs() < 1e-6);\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn mean_absolute_deviation(numbers: &[f64]) -> f64 {\n"
            "    let mean = numbers.iter().sum::<f64>() / numbers.len() as f64;\n"
            "    numbers.iter().map(|&x| (x - mean).abs()).sum::<f64>() / numbers.len() as f64\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/rust/9",
        "language": "rust",
        "entry_point": "truncate_number",
        "prompt": (
            "// Complete this Rust function.\n\n"
            "fn truncate_number(n: f64) -> f64 {\n"
            "    // your code here — return decimal part\n"
            "    todo!()\n"
            "}\n\n"
            "fn main() {\n"
            "    assert!((truncate_number(3.5) - 0.5).abs() < 1e-9);\n"
            "    assert!((truncate_number(1.33) - 0.33).abs() < 1e-4);\n"
            "    println!(\"PASS\");\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "fn truncate_number(n: f64) -> f64 {\n"
            "    n - n.floor()\n"
            "}\n"
        ),
    },
]


# ── Julia Problems ────────────────────────────────────────────────────────────
_JULIA_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/julia/0",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "has_close_elements",
        "prompt": (
            "# Complete this Julia function.\n"
            "# Return ONLY the complete function — no markdown, no explanation.\n\n"
            "# Check if any two numbers in the array are closer than threshold.\n"
            "function has_close_elements(numbers::Vector{Float64}, threshold::Float64)::Bool\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert has_close_elements([1.0, 2.0, 3.0], 0.5) == false\n"
            "@assert has_close_elements([1.0, 2.8, 3.0, 4.0], 0.3) == true\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function has_close_elements(numbers::Vector{Float64}, threshold::Float64)::Bool\n"
            "    n = length(numbers)\n"
            "    for i in 1:n, j in (i+1):n\n"
            "        abs(numbers[i] - numbers[j]) < threshold && return true\n"
            "    end\n"
            "    false\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/julia/1",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "below_zero",
        "prompt": (
            "# Complete this Julia function.\n\n"
            "# Return true if balance ever goes below zero.\n"
            "function below_zero(operations::Vector{Int})::Bool\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert below_zero([1, 2, 3]) == false\n"
            "@assert below_zero([1, 2, -4, 5]) == true\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function below_zero(operations::Vector{Int})::Bool\n"
            "    balance = 0\n"
            "    for op in operations\n"
            "        balance += op\n"
            "        balance < 0 && return true\n"
            "    end\n"
            "    false\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/julia/2",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "fibonacci",
        "prompt": (
            "# Complete this Julia function.\n\n"
            "# Return the nth Fibonacci number (0-indexed: fib(0)=0, fib(1)=1).\n"
            "function fibonacci(n::Int)::Int\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert fibonacci(0) == 0\n"
            "@assert fibonacci(1) == 1\n"
            "@assert fibonacci(5) == 5\n"
            "@assert fibonacci(10) == 55\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function fibonacci(n::Int)::Int\n"
            "    n <= 1 && return n\n"
            "    a, b = 0, 1\n"
            "    for _ in 2:n; a, b = b, a + b; end\n"
            "    b\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/julia/3",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "is_palindrome",
        "prompt": (
            "# Complete this Julia function.\n\n"
            "# Return true if the string is a palindrome.\n"
            "function is_palindrome(s::String)::Bool\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert is_palindrome(\"\") == true\n"
            "@assert is_palindrome(\"aba\") == true\n"
            "@assert is_palindrome(\"abc\") == false\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function is_palindrome(s::String)::Bool\n"
            "    s == reverse(s)\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/julia/4",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "mean_absolute_deviation",
        "prompt": (
            "# Complete this Julia function.\n\n"
            "# Return mean absolute deviation of a vector of numbers.\n"
            "function mean_absolute_deviation(numbers::Vector{Float64})::Float64\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert abs(mean_absolute_deviation([1.0, 2.0, 3.0]) - 2/3) < 1e-6\n"
            "@assert abs(mean_absolute_deviation([1.0, 2.0, 3.0, 4.0]) - 1.0) < 1e-6\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function mean_absolute_deviation(numbers::Vector{Float64})::Float64\n"
            "    m = sum(numbers) / length(numbers)\n"
            "    sum(abs.(numbers .- m)) / length(numbers)\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/julia/5",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "count_vowels",
        "prompt": (
            "# Complete this Julia function.\n\n"
            "# Return the number of vowels (aeiouAEIOU) in the string.\n"
            "function count_vowels(s::String)::Int\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert count_vowels(\"\") == 0\n"
            "@assert count_vowels(\"hello\") == 2\n"
            "@assert count_vowels(\"AEIOU\") == 5\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function count_vowels(s::String)::Int\n"
            "    count(c -> c in \"aeiouAEIOU\", s)\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/julia/6",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "intersperse",
        "prompt": (
            "# Complete this Julia function.\n\n"
            "# Insert delimiter between every two consecutive elements.\n"
            "# intersperse([1,2,3], 4) => [1,4,2,4,3]\n"
            "function intersperse(numbers::Vector{Int}, delimiter::Int)::Vector{Int}\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert intersperse(Int[], 4) == Int[]\n"
            "@assert intersperse([1, 2, 3], 4) == [1, 4, 2, 4, 3]\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function intersperse(numbers::Vector{Int}, delimiter::Int)::Vector{Int}\n"
            "    isempty(numbers) && return Int[]\n"
            "    result = Int[]\n"
            "    for (i, n) in enumerate(numbers)\n"
            "        push!(result, n)\n"
            "        i < length(numbers) && push!(result, delimiter)\n"
            "    end\n"
            "    result\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/julia/7",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "sum_product",
        "prompt": (
            "# Complete this Julia function.\n\n"
            "# Return (sum, product) of a vector. sum_product([]) => (0, 1)\n"
            "function sum_product(numbers::Vector{Int})::Tuple{Int,Int}\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert sum_product(Int[]) == (0, 1)\n"
            "@assert sum_product([1, 2, 3, 4]) == (10, 24)\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function sum_product(numbers::Vector{Int})::Tuple{Int,Int}\n"
            "    (sum(numbers; init=0), prod(numbers; init=1))\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/julia/8",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "max_element",
        "prompt": (
            "# Complete this Julia function.\n\n"
            "# Return the largest element in a non-empty vector.\n"
            "function max_element(arr::Vector{Int})::Int\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert max_element([3, 1, 4, 1, 5, 9]) == 9\n"
            "@assert max_element([-1, -5, -2]) == -1\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function max_element(arr::Vector{Int})::Int\n"
            "    maximum(arr)\n"
            "end\n"
        ),
    },
    {
        "task_id": "MultiPL-E/julia/9",
        "language": "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia",
        "entry_point": "truncate_number",
        "prompt": (
            "# Complete this Julia function.\n\n"
            "# Return the decimal part of a positive float.\n"
            "# truncate_number(3.5) == 0.5\n"
            "function truncate_number(n::Float64)::Float64\n"
            "    # your code here\n"
            "end\n"
        ),
        "test": (
            "@assert abs(truncate_number(3.5) - 0.5) < 1e-9\n"
            "@assert abs(truncate_number(1.33) - 0.33) < 1e-4\n"
            "println(\"ok\")\n"
        ),
        "canonical_solution": (
            "function truncate_number(n::Float64)::Float64\n"
            "    n - floor(n)\n"
            "end\n"
        ),
    },
]


# ── C# Problems ───────────────────────────────────────────────────────────────
_CS_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/cs/0",
        "language": "cs",
        "entry_point": "HasCloseElements",
        "prompt": (
            "// Complete this C# method.\n"
            "// Return ONLY the complete runnable C# program — no markdown.\n\n"
            "using System;\nusing System.Collections.Generic;\n\n"
            "class Solution {\n"
            "    public static bool HasCloseElements(List<double> numbers, double threshold) {\n"
            "        // your code here\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        System.Diagnostics.Debug.Assert(HasCloseElements(new List<double>{1.0,2.0,3.0}, 0.5) == false);\n"
            "        System.Diagnostics.Debug.Assert(HasCloseElements(new List<double>{1.0,2.8,3.0,4.0}, 0.3) == true);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static bool HasCloseElements(List<double> numbers, double threshold) {\n"
            "        for (int i = 0; i < numbers.Count; i++)\n"
            "            for (int j = i+1; j < numbers.Count; j++)\n"
            "                if (Math.Abs(numbers[i] - numbers[j]) < threshold) return true;\n"
            "        return false;\n"
            "    }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/cs/1",
        "language": "cs",
        "entry_point": "BelowZero",
        "prompt": (
            "// Complete this C# method.\n\n"
            "using System;\nusing System.Collections.Generic;\n\n"
            "class Solution {\n"
            "    public static bool BelowZero(List<int> operations) {\n"
            "        // your code here\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        System.Diagnostics.Debug.Assert(BelowZero(new List<int>{1,2,3}) == false);\n"
            "        System.Diagnostics.Debug.Assert(BelowZero(new List<int>{1,2,-4,5}) == true);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static bool BelowZero(List<int> operations) {\n"
            "        int balance = 0;\n"
            "        foreach (var op in operations) { balance += op; if (balance < 0) return true; }\n"
            "        return false;\n"
            "    }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/cs/2",
        "language": "cs",
        "entry_point": "Fibonacci",
        "prompt": (
            "// Complete this C# method.\n\n"
            "using System;\n\n"
            "class Solution {\n"
            "    public static long Fibonacci(int n) {\n"
            "        // your code here\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        System.Diagnostics.Debug.Assert(Fibonacci(0) == 0);\n"
            "        System.Diagnostics.Debug.Assert(Fibonacci(1) == 1);\n"
            "        System.Diagnostics.Debug.Assert(Fibonacci(5) == 5);\n"
            "        System.Diagnostics.Debug.Assert(Fibonacci(10) == 55);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static long Fibonacci(int n) {\n"
            "        if (n <= 1) return n;\n"
            "        long a = 0, b = 1;\n"
            "        for (int i = 2; i <= n; i++) { long t = b; b = a + b; a = t; }\n"
            "        return b;\n"
            "    }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/cs/3",
        "language": "cs",
        "entry_point": "IsPalindrome",
        "prompt": (
            "// Complete this C# method.\n\n"
            "using System;\n\n"
            "class Solution {\n"
            "    public static bool IsPalindrome(string s) {\n"
            "        // your code here\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        System.Diagnostics.Debug.Assert(IsPalindrome(\"\") == true);\n"
            "        System.Diagnostics.Debug.Assert(IsPalindrome(\"aba\") == true);\n"
            "        System.Diagnostics.Debug.Assert(IsPalindrome(\"abc\") == false);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static bool IsPalindrome(string s) {\n"
            "        var arr = s.ToCharArray();\n"
            "        Array.Reverse(arr);\n"
            "        return s == new string(arr);\n"
            "    }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/cs/4",
        "language": "cs",
        "entry_point": "CountVowels",
        "prompt": (
            "// Complete this C# method.\n\n"
            "using System;\n\n"
            "class Solution {\n"
            "    public static int CountVowels(string s) {\n"
            "        // your code here\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        System.Diagnostics.Debug.Assert(CountVowels(\"\") == 0);\n"
            "        System.Diagnostics.Debug.Assert(CountVowels(\"hello\") == 2);\n"
            "        System.Diagnostics.Debug.Assert(CountVowels(\"AEIOU\") == 5);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static int CountVowels(string s) {\n"
            "        int count = 0;\n"
            "        foreach (char c in s) if (\"aeiouAEIOU\".IndexOf(c) >= 0) count++;\n"
            "        return count;\n"
            "    }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/cs/5",
        "language": "cs",
        "entry_point": "MeanAbsoluteDeviation",
        "prompt": (
            "// Complete this C# method.\n\n"
            "using System;\nusing System.Collections.Generic;\nusing System.Linq;\n\n"
            "class Solution {\n"
            "    public static double MeanAbsoluteDeviation(List<double> numbers) {\n"
            "        // your code here\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        System.Diagnostics.Debug.Assert(Math.Abs(MeanAbsoluteDeviation(new List<double>{1,2,3}) - 2.0/3.0) < 1e-6);\n"
            "        System.Diagnostics.Debug.Assert(Math.Abs(MeanAbsoluteDeviation(new List<double>{1,2,3,4}) - 1.0) < 1e-6);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static double MeanAbsoluteDeviation(List<double> numbers) {\n"
            "        double mean = numbers.Average();\n"
            "        return numbers.Select(x => Math.Abs(x - mean)).Average();\n"
            "    }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/cs/6",
        "language": "cs",
        "entry_point": "Intersperse",
        "prompt": (
            "// Complete this C# method.\n\n"
            "using System;\nusing System.Collections.Generic;\n\n"
            "class Solution {\n"
            "    public static List<int> Intersperse(List<int> numbers, int delimiter) {\n"
            "        // your code here\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        var r1 = Intersperse(new List<int>(), 4);\n"
            "        System.Diagnostics.Debug.Assert(r1.Count == 0);\n"
            "        var r2 = Intersperse(new List<int>{1,2,3}, 4);\n"
            "        System.Diagnostics.Debug.Assert(r2.Count == 5 && r2[0]==1 && r2[1]==4 && r2[2]==2);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static List<int> Intersperse(List<int> numbers, int delimiter) {\n"
            "        var result = new List<int>();\n"
            "        for (int i = 0; i < numbers.Count; i++) {\n"
            "            result.Add(numbers[i]);\n"
            "            if (i + 1 < numbers.Count) result.Add(delimiter);\n"
            "        }\n"
            "        return result;\n"
            "    }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/cs/7",
        "language": "cs",
        "entry_point": "SumProduct",
        "prompt": (
            "// Complete this C# method.\n\n"
            "using System;\nusing System.Collections.Generic;\nusing System.Linq;\n\n"
            "class Solution {\n"
            "    public static (long, long) SumProduct(List<int> numbers) {\n"
            "        // your code here — return (sum, product)\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        var (s0, p0) = SumProduct(new List<int>());\n"
            "        System.Diagnostics.Debug.Assert(s0 == 0 && p0 == 1);\n"
            "        var (s1, p1) = SumProduct(new List<int>{1,2,3,4});\n"
            "        System.Diagnostics.Debug.Assert(s1 == 10 && p1 == 24);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static (long, long) SumProduct(List<int> numbers) {\n"
            "        long s = numbers.Sum(x => (long)x);\n"
            "        long p = numbers.Aggregate(1L, (acc, x) => acc * x);\n"
            "        return (s, p);\n"
            "    }\n"
        ),
    },
    {
        "task_id": "MultiPL-E/cs/8",
        "language": "cs",
        "entry_point": "MaxElement",
        "prompt": (
            "// Complete this C# method.\n\n"
            "using System;\nusing System.Collections.Generic;\nusing System.Linq;\n\n"
            "class Solution {\n"
            "    public static int MaxElement(List<int> arr) {\n"
            "        // your code here — arr is guaranteed non-empty\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        System.Diagnostics.Debug.Assert(MaxElement(new List<int>{3,1,4,1,5,9}) == 9);\n"
            "        System.Diagnostics.Debug.Assert(MaxElement(new List<int>{-1,-5,-2}) == -1);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static int MaxElement(List<int> arr) => arr.Max();\n"
        ),
    },
    {
        "task_id": "MultiPL-E/cs/9",
        "language": "cs",
        "entry_point": "TruncateNumber",
        "prompt": (
            "// Complete this C# method.\n\n"
            "using System;\n\n"
            "class Solution {\n"
            "    public static double TruncateNumber(double n) {\n"
            "        // your code here — return decimal part\n"
            "        throw new NotImplementedException();\n"
            "    }\n\n"
            "    static void Main() {\n"
            "        System.Diagnostics.Debug.Assert(Math.Abs(TruncateNumber(3.5) - 0.5) < 1e-9);\n"
            "        System.Diagnostics.Debug.Assert(Math.Abs(TruncateNumber(1.33) - 0.33) < 1e-4);\n"
            "        Console.WriteLine(\"PASS\");\n"
            "    }\n"
            "}\n"
        ),
        "test": "",
        "canonical_solution": (
            "    public static double TruncateNumber(double n) => n - Math.Floor(n);\n"
        ),
    },
]


_BASH_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/bash/0",
        "language": "bash",
        "entry_point": "has_close_elements",
        "prompt": (
            "# Complete this Bash function.\n"
            "# has_close_elements: given a space-separated list of numbers and a threshold,\n"
            "# echo 'true' if any two numbers are closer than threshold, else echo 'false'.\n"
            "# $1 = space-separated numbers, $2 = threshold\n\n"
            "has_close_elements() {\n"
            "    local nums=\"$1\"\n"
            "    local threshold=\"$2\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(has_close_elements \"1.0 2.0 3.0\" \"0.5\")\n"
            "[[ \"$result\" == \"false\" ]] || { echo \"FAIL test1: got $result\"; exit 1; }\n"
            "result=$(has_close_elements \"1.0 2.8 3.0 4.0 5.0 2.0\" \"0.3\")\n"
            "[[ \"$result\" == \"true\" ]] || { echo \"FAIL test2: got $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "has_close_elements() {\n"
            "    local nums=\"$1\"; local threshold=\"$2\"\n"
            "    read -ra arr <<< \"$nums\"; local n=${#arr[@]}\n"
            "    for (( i=0; i<n; i++ )); do\n"
            "        for (( j=i+1; j<n; j++ )); do\n"
            "            local d; d=$(awk \"BEGIN{d=${arr[$i]}-${arr[$j]}; if(d<0)d=-d; print (d<$threshold)?\\\"true\\\":\\\"false\\\"}\")\n"
            "            [[ \"$d\" == \"true\" ]] && { echo true; return; }\n"
            "        done\n"
            "    done\n"
            "    echo false\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/1",
        "language": "bash",
        "entry_point": "separate_paren_groups",
        "prompt": (
            "# Complete this Bash function.\n"
            "# separate_paren_groups: given a string of nested parentheses (may contain spaces),\n"
            "# echo each top-level balanced group separated by spaces.\n"
            "# $1 = input string\n\n"
            "separate_paren_groups() {\n"
            "    local s=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(separate_paren_groups \"( ) (( )) (( )( ))\")\n"
            "[[ \"$result\" == \"() (()) (()())\" ]] || { echo \"FAIL: got '$result'\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "separate_paren_groups() {\n"
            "    local s=\"${1// /}\"; local depth=0 start=0 result=\"\"\n"
            "    local len=${#s}\n"
            "    for (( i=0; i<len; i++ )); do\n"
            "        local c=\"${s:$i:1}\"\n"
            "        if [[ \"$c\" == \"(\" ]]; then\n"
            "            (( depth == 0 )) && start=$i; (( depth++ )) || true\n"
            "        elif [[ \"$c\" == \")\" ]]; then\n"
            "            (( depth-- )) || true\n"
            "            if (( depth == 0 )); then\n"
            "                local g=\"${s:$start:$((i-start+1))}\"\n"
            "                result=${result:+\"$result \"}\"$g\"\n"
            "            fi\n"
            "        fi\n"
            "    done\n"
            "    echo \"$result\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/2",
        "language": "bash",
        "entry_point": "truncate_number",
        "prompt": (
            "# Complete this Bash function.\n"
            "# truncate_number: given a positive float, echo only the decimal part.\n"
            "# e.g. truncate_number 3.5 => 0.5\n"
            "# $1 = float number\n\n"
            "truncate_number() {\n"
            "    local n=\"$1\"\n"
            "    # your code here (use awk or bc for float arithmetic)\n"
            "}\n"
        ),
        "test": (
            "result=$(truncate_number \"3.5\")\n"
            "[[ \"$result\" == \"0.5\" ]] || { echo \"FAIL 3.5: got $result\"; exit 1; }\n"
            "ok=$(awk \"BEGIN{print ($result > 0.32 && $result < 0.34) ? \\\"ok\\\" : \\\"fail\\\"}\")\n"
            "result2=$(truncate_number \"1.33\")\n"
            "ok2=$(awk \"BEGIN{print ($result2 > 0.329 && $result2 < 0.331) ? \\\"ok\\\" : \\\"fail\\\"}\")\n"
            "[[ \"$ok2\" == \"ok\" ]] || { echo \"FAIL 1.33: got $result2\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "truncate_number() {\n"
            "    awk \"BEGIN{printf \\\"%.10g\\\\n\\\", $1 - int($1)}\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/3",
        "language": "bash",
        "entry_point": "below_zero",
        "prompt": (
            "# Complete this Bash function.\n"
            "# below_zero: given a space-separated list of integer operations applied to\n"
            "# a bank account starting at 0, echo 'true' if the balance ever goes below\n"
            "# zero, else echo 'false'.\n"
            "# $1 = space-separated integers\n\n"
            "below_zero() {\n"
            "    local ops=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(below_zero \"1 2 3\")\n"
            "[[ \"$result\" == \"false\" ]] || { echo \"FAIL test1: got $result\"; exit 1; }\n"
            "result=$(below_zero \"1 2 -4 5\")\n"
            "[[ \"$result\" == \"true\" ]] || { echo \"FAIL test2: got $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "below_zero() {\n"
            "    read -ra arr <<< \"$1\"; local bal=0\n"
            "    for op in \"${arr[@]}\"; do\n"
            "        (( bal += op )) || true\n"
            "        (( bal < 0 )) && { echo true; return; } || true\n"
            "    done\n"
            "    echo false\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/4",
        "language": "bash",
        "entry_point": "mean_absolute_deviation",
        "prompt": (
            "# Complete this Bash function.\n"
            "# mean_absolute_deviation: given a space-separated list of numbers,\n"
            "# compute and echo the Mean Absolute Deviation (MAD).\n"
            "# $1 = space-separated floats\n\n"
            "mean_absolute_deviation() {\n"
            "    local nums=\"$1\"\n"
            "    # your code here (use awk for float arithmetic; use (d<0?-d:d) not abs())\n"
            "}\n"
        ),
        "test": (
            "result=$(mean_absolute_deviation \"1.0 2.0 3.0 4.0\")\n"
            "ok=$(awk \"BEGIN{print ($result > 0.99 && $result < 1.01) ? \\\"ok\\\" : \\\"fail\\\"}\")\n"
            "[[ \"$ok\" == \"ok\" ]] || { echo \"FAIL: got $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "mean_absolute_deviation() {\n"
            "    awk -v data=\"$1\" 'BEGIN{\n"
            "        n=split(data,a); s=0\n"
            "        for(i=1;i<=n;i++) s+=a[i]; mean=s/n\n"
            "        mad=0; for(i=1;i<=n;i++){d=a[i]-mean; if(d<0)d=-d; mad+=d}\n"
            "        print mad/n\n"
            "    }'\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/5",
        "language": "bash",
        "entry_point": "intersperse",
        "prompt": (
            "# Complete this Bash function.\n"
            "# intersperse: given a space-separated list of numbers and a delimiter number,\n"
            "# echo the list with the delimiter inserted between every pair of elements.\n"
            "# e.g. intersperse '1 2 3' 4 => '1 4 2 4 3'\n"
            "# $1 = space-separated numbers, $2 = delimiter\n\n"
            "intersperse() {\n"
            "    local nums=\"$1\"\n"
            "    local delim=\"$2\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(intersperse \"1 2 3\" \"4\")\n"
            "[[ \"$result\" == \"1 4 2 4 3\" ]] || { echo \"FAIL test1: got $result\"; exit 1; }\n"
            "result=$(intersperse \"\" \"7\")\n"
            "[[ \"$result\" == \"\" ]] || { echo \"FAIL empty: got $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "intersperse() {\n"
            "    read -ra arr <<< \"$1\"; local delim=\"$2\" result=\"\" first=1\n"
            "    for n in \"${arr[@]}\"; do\n"
            "        if (( first )); then result=\"$n\"; first=0\n"
            "        else result=\"$result $delim $n\"; fi\n"
            "    done\n"
            "    echo \"$result\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/6",
        "language": "bash",
        "entry_point": "parse_nested_parens",
        "prompt": (
            "# Complete this Bash function.\n"
            "# parse_nested_parens: given a string of space-separated paren groups,\n"
            "# echo the maximum nesting depth of each group, space-separated.\n"
            "# e.g. parse_nested_parens '(()()) ((()))' => '2 3'\n"
            "# $1 = space-separated paren groups\n\n"
            "parse_nested_parens() {\n"
            "    local s=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(parse_nested_parens \"(()()) ((())) () ((())(()))\")\n"
            "[[ \"$result\" == \"2 3 1 3\" ]] || { echo \"FAIL: got $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "parse_nested_parens() {\n"
            "    read -ra groups <<< \"$1\"; local result=\"\"\n"
            "    for group in \"${groups[@]}\"; do\n"
            "        local max_d=0 depth=0 len=${#group}\n"
            "        for (( i=0; i<len; i++ )); do\n"
            "            local c=\"${group:$i:1}\"\n"
            "            if [[ \"$c\" == \"(\" ]]; then\n"
            "                (( depth++ )) || true\n"
            "                (( depth > max_d )) && max_d=$depth || true\n"
            "            elif [[ \"$c\" == \")\" ]]; then (( depth-- )) || true; fi\n"
            "        done\n"
            "        result=${result:+\"$result \"}\"$max_d\"\n"
            "    done\n"
            "    echo \"$result\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/7",
        "language": "bash",
        "entry_point": "filter_by_substring",
        "prompt": (
            "# Complete this Bash function.\n"
            "# filter_by_substring: given a space-separated list of strings and a substring,\n"
            "# print each string (one per line) that contains the substring.\n"
            "# $1 = space-separated strings, $2 = substring\n\n"
            "filter_by_substring() {\n"
            "    local strings=\"$1\"\n"
            "    local substring=\"$2\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(filter_by_substring \"abc def bcd efg\" \"bc\")\n"
            "expected=\"$(printf 'abc\\nbcd')\"\n"
            "[[ \"$result\" == \"$expected\" ]] || { echo \"FAIL: got '$result'\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "filter_by_substring() {\n"
            "    read -ra arr <<< \"$1\"\n"
            "    for s in \"${arr[@]}\"; do\n"
            "        [[ \"$s\" == *\"$2\"* ]] && echo \"$s\" || true\n"
            "    done\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/8",
        "language": "bash",
        "entry_point": "sum_product",
        "prompt": (
            "# Complete this Bash function.\n"
            "# sum_product: given a space-separated list of numbers,\n"
            "# echo the sum and product on one line separated by a space.\n"
            "# e.g. sum_product '1 2 3 4' => '10 24'\n"
            "# $1 = space-separated numbers\n\n"
            "sum_product() {\n"
            "    local nums=\"$1\"\n"
            "    # your code here (use awk for arithmetic)\n"
            "}\n"
        ),
        "test": (
            "result=$(sum_product \"1 2 3 4\")\n"
            "[[ \"$result\" == \"10 24\" ]] || { echo \"FAIL: got $result\"; exit 1; }\n"
            "result=$(sum_product \"\")\n"
            "[[ \"$result\" == \"0 1\" ]] || { echo \"FAIL empty: got $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "sum_product() {\n"
            "    awk -v data=\"$1\" 'BEGIN{\n"
            "        n=split(data,a); s=0; p=1\n"
            "        for(i=1;i<=n;i++){s+=a[i]; p*=a[i]}\n"
            "        print s, p\n"
            "    }'\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/9",
        "language": "bash",
        "entry_point": "rolling_max",
        "prompt": (
            "# Complete this Bash function.\n"
            "# rolling_max: given a space-separated list of numbers, echo the running\n"
            "# maximum at each position, space-separated.\n"
            "# e.g. rolling_max '1 2 3 2 3 4 2' => '1 2 3 3 3 4 4'\n"
            "# $1 = space-separated numbers\n\n"
            "rolling_max() {\n"
            "    local nums=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(rolling_max \"1 2 3 2 3 4 2\")\n"
            "[[ \"$result\" == \"1 2 3 3 3 4 4\" ]] || { echo \"FAIL: got $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "rolling_max() {\n"
            "    read -ra arr <<< \"$1\"; local result=\"\" cur_max=\"\"\n"
            "    for n in \"${arr[@]}\"; do\n"
            "        if [[ -z \"$cur_max\" ]]; then cur_max=$n\n"
            "        else cur_max=$(awk \"BEGIN{print ($n > $cur_max) ? $n : $cur_max}\"); fi\n"
            "        result=${result:+\"$result \"}\"$cur_max\"\n"
            "    done\n"
            "    echo \"$result\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/10",
        "language": "bash",
        "entry_point": "is_palindrome",
        "prompt": (
            "# Complete this Bash function.\n"
            "# is_palindrome: echo 'true' if the string is a palindrome, else 'false'.\n"
            "# $1 = string\n\n"
            "is_palindrome() {\n"
            "    local s=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(is_palindrome \"abba\")\n"
            "[[ \"$result\" == \"true\" ]] || { echo \"FAIL abba: $result\"; exit 1; }\n"
            "result=$(is_palindrome \"hello\")\n"
            "[[ \"$result\" == \"false\" ]] || { echo \"FAIL hello: $result\"; exit 1; }\n"
            "result=$(is_palindrome \"racecar\")\n"
            "[[ \"$result\" == \"true\" ]] || { echo \"FAIL racecar: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "is_palindrome() {\n"
            "    local s=\"$1\"\n"
            "    local rev; rev=$(echo \"$s\" | rev)\n"
            "    [[ \"$s\" == \"$rev\" ]] && echo true || echo false\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/11",
        "language": "bash",
        "entry_point": "make_palindrome",
        "prompt": (
            "# Complete this Bash function.\n"
            "# make_palindrome: find the shortest palindrome that begins with the given string.\n"
            "# Append the reverse of the longest non-palindromic prefix to the end.\n"
            "# e.g. make_palindrome 'cat' => 'catac'\n"
            "# $1 = string\n\n"
            "make_palindrome() {\n"
            "    local s=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(make_palindrome \"\")\n"
            "[[ \"$result\" == \"\" ]] || { echo \"FAIL empty: $result\"; exit 1; }\n"
            "result=$(make_palindrome \"cat\")\n"
            "[[ \"$result\" == \"catac\" ]] || { echo \"FAIL cat: $result\"; exit 1; }\n"
            "result=$(make_palindrome \"cata\")\n"
            "[[ \"$result\" == \"catac\" ]] || { echo \"FAIL cata: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "make_palindrome() {\n"
            "    local s=\"$1\"; local len=${#s}\n"
            "    for (( i=0; i<=len; i++ )); do\n"
            "        local suffix=\"${s:$i}\"\n"
            "        local rev; rev=$(echo \"$suffix\" | rev)\n"
            "        if [[ \"$suffix\" == \"$rev\" ]]; then\n"
            "            local prefix=\"${s:0:$i}\"\n"
            "            local pref_rev; pref_rev=$(echo \"$prefix\" | rev)\n"
            "            echo \"${s}${pref_rev}\"; return\n"
            "        fi\n"
            "    done\n"
            "    echo \"$s\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/12",
        "language": "bash",
        "entry_point": "string_xor",
        "prompt": (
            "# Complete this Bash function.\n"
            "# string_xor: given two binary strings of equal length (containing '0' and '1'),\n"
            "# echo their XOR result as a binary string.\n"
            "# e.g. string_xor '010' '110' => '100'\n"
            "# $1 = first binary string, $2 = second binary string\n\n"
            "string_xor() {\n"
            "    local a=\"$1\"\n"
            "    local b=\"$2\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(string_xor \"010\" \"110\")\n"
            "[[ \"$result\" == \"100\" ]] || { echo \"FAIL test1: $result\"; exit 1; }\n"
            "result=$(string_xor \"0000\" \"1111\")\n"
            "[[ \"$result\" == \"1111\" ]] || { echo \"FAIL test2: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "string_xor() {\n"
            "    local a=\"$1\" b=\"$2\" result=\"\"\n"
            "    local len=${#a}\n"
            "    for (( i=0; i<len; i++ )); do\n"
            "        if [[ \"${a:$i:1}\" == \"${b:$i:1}\" ]]; then result+=\"0\"\n"
            "        else result+=\"1\"; fi\n"
            "    done\n"
            "    echo \"$result\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/13",
        "language": "bash",
        "entry_point": "longest",
        "prompt": (
            "# Complete this Bash function.\n"
            "# longest: given a space-separated list of strings, echo the longest one.\n"
            "# If there is a tie, echo the first longest string.\n"
            "# $1 = space-separated strings\n\n"
            "longest() {\n"
            "    local strings=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(longest \"a bb ccc\")\n"
            "[[ \"$result\" == \"ccc\" ]] || { echo \"FAIL test1: $result\"; exit 1; }\n"
            "result=$(longest \"abc de f\")\n"
            "[[ \"$result\" == \"abc\" ]] || { echo \"FAIL test2: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "longest() {\n"
            "    read -ra arr <<< \"$1\"; local best=\"\"\n"
            "    for s in \"${arr[@]}\"; do\n"
            "        (( ${#s} > ${#best} )) && best=\"$s\" || true\n"
            "    done\n"
            "    echo \"$best\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/14",
        "language": "bash",
        "entry_point": "greatest_common_divisor",
        "prompt": (
            "# Complete this Bash function.\n"
            "# greatest_common_divisor: echo the GCD of two positive integers.\n"
            "# $1 = first integer, $2 = second integer\n\n"
            "greatest_common_divisor() {\n"
            "    local a=$1\n"
            "    local b=$2\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(greatest_common_divisor 3 5)\n"
            "[[ \"$result\" == \"1\" ]] || { echo \"FAIL 3 5: $result\"; exit 1; }\n"
            "result=$(greatest_common_divisor 25 15)\n"
            "[[ \"$result\" == \"5\" ]] || { echo \"FAIL 25 15: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "greatest_common_divisor() {\n"
            "    local a=$1 b=$2\n"
            "    while (( b != 0 )); do\n"
            "        local t=$b; b=$(( a % b )); a=$t\n"
            "    done\n"
            "    echo $a\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/15",
        "language": "bash",
        "entry_point": "all_prefixes",
        "prompt": (
            "# Complete this Bash function.\n"
            "# all_prefixes: echo all prefixes of the input string, space-separated,\n"
            "# from shortest to longest.\n"
            "# e.g. all_prefixes 'abc' => 'a ab abc'\n"
            "# $1 = string\n\n"
            "all_prefixes() {\n"
            "    local s=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(all_prefixes \"abc\")\n"
            "[[ \"$result\" == \"a ab abc\" ]] || { echo \"FAIL: $result\"; exit 1; }\n"
            "result=$(all_prefixes \"a\")\n"
            "[[ \"$result\" == \"a\" ]] || { echo \"FAIL single: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "all_prefixes() {\n"
            "    local s=\"$1\" result=\"\" len=${#1}\n"
            "    for (( i=1; i<=len; i++ )); do\n"
            "        result=${result:+\"$result \"}\"${s:0:$i}\"\n"
            "    done\n"
            "    echo \"$result\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/16",
        "language": "bash",
        "entry_point": "string_sequence",
        "prompt": (
            "# Complete this Bash function.\n"
            "# string_sequence: given a non-negative integer n, echo '0 1 2 ... n'\n"
            "# as a space-separated sequence.\n"
            "# $1 = n\n\n"
            "string_sequence() {\n"
            "    local n=$1\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(string_sequence 5)\n"
            "[[ \"$result\" == \"0 1 2 3 4 5\" ]] || { echo \"FAIL 5: $result\"; exit 1; }\n"
            "result=$(string_sequence 0)\n"
            "[[ \"$result\" == \"0\" ]] || { echo \"FAIL 0: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "string_sequence() {\n"
            "    seq 0 $1 | tr '\\n' ' ' | sed 's/ $//'\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/17",
        "language": "bash",
        "entry_point": "count_distinct_characters",
        "prompt": (
            "# Complete this Bash function.\n"
            "# count_distinct_characters: echo the count of distinct characters\n"
            "# in the string, treating uppercase and lowercase as the same.\n"
            "# e.g. count_distinct_characters 'xyzXYZ' => 3\n"
            "# $1 = string\n\n"
            "count_distinct_characters() {\n"
            "    local s=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(count_distinct_characters \"xyzXYZ\")\n"
            "[[ \"$result\" == \"3\" ]] || { echo \"FAIL xyzXYZ: $result\"; exit 1; }\n"
            "result=$(count_distinct_characters \"Jerry\")\n"
            "[[ \"$result\" == \"4\" ]] || { echo \"FAIL Jerry: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "count_distinct_characters() {\n"
            "    echo \"$1\" | tr '[:upper:]' '[:lower:]' | grep -o . | sort -u | wc -l | tr -d ' '\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/18",
        "language": "bash",
        "entry_point": "parse_music",
        "prompt": (
            "# Complete this Bash function.\n"
            "# parse_music: given a string of music note tokens separated by spaces,\n"
            "# convert each token to its beat duration and echo them space-separated.\n"
            "# 'o' = 4 beats, 'o|' = 2 beats, '.|' = 1 beat.\n"
            "# $1 = space-separated note tokens\n\n"
            "parse_music() {\n"
            "    local s=\"$1\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(parse_music \"o o| .| o| o| .| .| .| .| o o\")\n"
            "[[ \"$result\" == \"4 2 1 2 2 1 1 1 1 4 4\" ]] || { echo \"FAIL: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "parse_music() {\n"
            "    read -ra tokens <<< \"$1\"; local result=\"\" b\n"
            "    for t in \"${tokens[@]}\"; do\n"
            "        if [[ \"$t\" == \"o\" ]]; then b=4\n"
            "        elif [[ \"$t\" == \"o|\" ]]; then b=2\n"
            "        elif [[ \"$t\" == \".|\" ]]; then b=1\n"
            "        else b=0; fi\n"
            "        result=${result:+\"$result \"}\"$b\"\n"
            "    done\n"
            "    echo \"$result\"\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/bash/19",
        "language": "bash",
        "entry_point": "how_many_times",
        "prompt": (
            "# Complete this Bash function.\n"
            "# how_many_times: count overlapping occurrences of substring in string.\n"
            "# e.g. how_many_times 'aaa' 'aa' => 2\n"
            "# $1 = string, $2 = substring\n\n"
            "how_many_times() {\n"
            "    local s=\"$1\"\n"
            "    local sub=\"$2\"\n"
            "    # your code here\n"
            "}\n"
        ),
        "test": (
            "result=$(how_many_times \"aaa\" \"a\")\n"
            "[[ \"$result\" == \"3\" ]] || { echo \"FAIL aaa/a: $result\"; exit 1; }\n"
            "result=$(how_many_times \"aaa\" \"aa\")\n"
            "[[ \"$result\" == \"2\" ]] || { echo \"FAIL aaa/aa: $result\"; exit 1; }\n"
            "result=$(how_many_times \"\" \"a\")\n"
            "[[ \"$result\" == \"0\" ]] || { echo \"FAIL empty: $result\"; exit 1; }\n"
            "echo PASS\n"
        ),
        "canonical_solution": (
            "how_many_times() {\n"
            "    local s=\"$1\" sub=\"$2\" count=0\n"
            "    local slen=${#s} sublen=${#sub}\n"
            "    (( sublen == 0 )) && { echo 0; return; } || true\n"
            "    for (( i=0; i<=slen-sublen; i++ )); do\n"
            "        [[ \"${s:$i:$sublen}\" == \"$sub\" ]] && (( count++ )) || true\n"
            "    done\n"
            "    echo $count\n"
            "}\n"
        ),
    },
]


_SWIFT_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/swift/0",
        "language": "swift",
        "entry_point": "hasCloseElements",
        "prompt": (
            "// Return true if any two numbers in `numbers` are closer than `threshold`.\n"
            "func hasCloseElements(_ numbers: [Double], threshold: Double) -> Bool {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(hasCloseElements([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], threshold: 0.3) == true)\n"
            "assert(hasCloseElements([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], threshold: 0.05) == false)\n"
            "assert(hasCloseElements([1.0, 2.0, 5.9, 4.0, 5.0], threshold: 0.95) == true)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func hasCloseElements(_ numbers: [Double], threshold: Double) -> Bool {\n"
            "    for i in 0..<numbers.count {\n"
            "        for j in (i+1)..<numbers.count {\n"
            "            if abs(numbers[i] - numbers[j]) < threshold { return true }\n"
            "        }\n"
            "    }\n"
            "    return false\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/2",
        "language": "swift",
        "entry_point": "truncateNumber",
        "prompt": (
            "// Return the fractional part of `number`.\n"
            "func truncateNumber(_ number: Double) -> Double {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(truncateNumber(3.5) == 0.5)\n"
            "assert(truncateNumber(1.25) == 0.25)\n"
            "assert(truncateNumber(123.0) == 0.0)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func truncateNumber(_ number: Double) -> Double {\n"
            "    return number.truncatingRemainder(dividingBy: 1.0)\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/3",
        "language": "swift",
        "entry_point": "belowZero",
        "prompt": (
            "// Return true if the running balance ever goes below zero.\n"
            "func belowZero(operations: [Int]) -> Bool {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(belowZero(operations: [1, 2, 3]) == false)\n"
            "assert(belowZero(operations: [1, 2, -4, 5]) == true)\n"
            "assert(belowZero(operations: []) == false)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func belowZero(operations: [Int]) -> Bool {\n"
            "    var balance = 0\n"
            "    for op in operations { balance += op; if balance < 0 { return true } }\n"
            "    return false\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/4",
        "language": "swift",
        "entry_point": "meanAbsoluteDeviation",
        "prompt": (
            "// Return the mean absolute deviation of the list.\n"
            "func meanAbsoluteDeviation(numbers: [Double]) -> Double {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(abs(meanAbsoluteDeviation(numbers: [1.0, 2.0, 3.0]) - 0.6667) < 0.001)\n"
            "assert(abs(meanAbsoluteDeviation(numbers: [1.0, 2.0, 3.0, 4.0]) - 1.0) < 0.001)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func meanAbsoluteDeviation(numbers: [Double]) -> Double {\n"
            "    let mean = numbers.reduce(0, +) / Double(numbers.count)\n"
            "    return numbers.map { abs($0 - mean) }.reduce(0, +) / Double(numbers.count)\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/6",
        "language": "swift",
        "entry_point": "parseNestedParens",
        "prompt": (
            "// For each space-separated group of parentheses, return the max nesting depth.\n"
            "func parseNestedParens(parenString: String) -> [Int] {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(parseNestedParens(parenString: \"(()()) ((())) () ((())(()))\") == [2, 3, 1, 3])\n"
            "assert(parseNestedParens(parenString: \"() (()) ((())) (((())))\") == [1, 2, 3, 4])\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func parseNestedParens(parenString: String) -> [Int] {\n"
            "    return parenString.split(separator: \" \").map { group -> Int in\n"
            "        var depth = 0, max = 0\n"
            "        for c in group { if c == \"(\" { depth += 1; if depth > max { max = depth } } else { depth -= 1 } }\n"
            "        return max\n"
            "    }\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/7",
        "language": "swift",
        "entry_point": "filterBySubstring",
        "prompt": (
            "// Return only the strings that contain `substring`.\n"
            "func filterBySubstring(strings: [String], substring: String) -> [String] {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(filterBySubstring(strings: [\"abc\", \"bacd\", \"cde\", \"array\"], substring: \"a\") == [\"abc\", \"bacd\", \"array\"])\n"
            "assert(filterBySubstring(strings: [], substring: \"a\") == [])\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func filterBySubstring(strings: [String], substring: String) -> [String] {\n"
            "    return strings.filter { $0.contains(substring) }\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/8",
        "language": "swift",
        "entry_point": "sumProduct",
        "prompt": (
            "// Return a tuple of (sum, product) of the integers.\n"
            "func sumProduct(numbers: [Int]) -> (Int, Int) {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "let r0 = sumProduct(numbers: []); assert(r0 == (0, 1))\n"
            "let r1 = sumProduct(numbers: [1, 2, 3, 4]); assert(r1 == (10, 24))\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func sumProduct(numbers: [Int]) -> (Int, Int) {\n"
            "    return (numbers.reduce(0, +), numbers.reduce(1, *))\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/10",
        "language": "swift",
        "entry_point": "isPalindrome",
        "prompt": (
            "// Return true if `string` is a palindrome.\n"
            "func isPalindrome(_ string: String) -> Bool {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(isPalindrome(\"\") == true)\n"
            "assert(isPalindrome(\"a\") == true)\n"
            "assert(isPalindrome(\"aba\") == true)\n"
            "assert(isPalindrome(\"ab\") == false)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func isPalindrome(_ string: String) -> Bool {\n"
            "    return string == String(string.reversed())\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/14",
        "language": "swift",
        "entry_point": "greatestCommonDivisor",
        "prompt": (
            "// Return the GCD of two integers.\n"
            "func greatestCommonDivisor(_ a: Int, _ b: Int) -> Int {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(greatestCommonDivisor(3, 7) == 1)\n"
            "assert(greatestCommonDivisor(10, 15) == 5)\n"
            "assert(greatestCommonDivisor(49, 14) == 7)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func greatestCommonDivisor(_ a: Int, _ b: Int) -> Int {\n"
            "    var a = a, b = b; while b != 0 { let t = b; b = a % b; a = t }; return a\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/15",
        "language": "swift",
        "entry_point": "allPrefixes",
        "prompt": (
            "// Return all prefixes of `string` from shortest to longest.\n"
            "func allPrefixes(string: String) -> [String] {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(allPrefixes(string: \"abc\") == [\"a\", \"ab\", \"abc\"])\n"
            "assert(allPrefixes(string: \"\") == [])\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func allPrefixes(string: String) -> [String] {\n"
            "    var result: [String] = []\n"
            "    for i in string.indices { result.append(String(string[...i])) }\n"
            "    return result\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/16",
        "language": "swift",
        "entry_point": "stringSequence",
        "prompt": (
            "// Return the space-separated string \"0 1 2 ... n\".\n"
            "func stringSequence(n: Int) -> String {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(stringSequence(n: 0) == \"0\")\n"
            "assert(stringSequence(n: 5) == \"0 1 2 3 4 5\")\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func stringSequence(n: Int) -> String {\n"
            "    return (0...n).map { String($0) }.joined(separator: \" \")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/17",
        "language": "swift",
        "entry_point": "countDistinctCharacters",
        "prompt": (
            "// Return the number of distinct characters in `string` (case-insensitive).\n"
            "func countDistinctCharacters(string: String) -> Int {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(countDistinctCharacters(string: \"xyzXYZ\") == 3)\n"
            "assert(countDistinctCharacters(string: \"Jerry\") == 4)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func countDistinctCharacters(string: String) -> Int {\n"
            "    return Set(string.lowercased()).count\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/19",
        "language": "swift",
        "entry_point": "howManyTimes",
        "prompt": (
            "// Count overlapping occurrences of `substring` in `string`.\n"
            "func howManyTimes(string: String, substring: String) -> Int {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(howManyTimes(string: \"\", substring: \"a\") == 0)\n"
            "assert(howManyTimes(string: \"aaa\", substring: \"a\") == 3)\n"
            "assert(howManyTimes(string: \"aaa\", substring: \"aa\") == 2)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func howManyTimes(string: String, substring: String) -> Int {\n"
            "    guard !substring.isEmpty else { return 0 }\n"
            "    var count = 0\n"
            "    var searchRange = string.startIndex..<string.endIndex\n"
            "    while let range = string.range(of: substring, range: searchRange) {\n"
            "        count += 1\n"
            "        searchRange = string.index(after: range.lowerBound)..<string.endIndex\n"
            "        if searchRange.lowerBound >= string.endIndex { break }\n"
            "    }\n"
            "    return count\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/20",
        "language": "swift",
        "entry_point": "sortNumbers",
        "prompt": (
            "// Sort a space-separated string of number words (zero..nine) and return sorted string.\n"
            "func sortNumbers(numbers: String) -> String {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(sortNumbers(numbers: \"three one five\") == \"one three five\")\n"
            "assert(sortNumbers(numbers: \"\") == \"\")\n"
            "assert(sortNumbers(numbers: \"zero\") == \"zero\")\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func sortNumbers(numbers: String) -> String {\n"
            "    let order = [\"zero\":0,\"one\":1,\"two\":2,\"three\":3,\"four\":4,\"five\":5,\"six\":6,\"seven\":7,\"eight\":8,\"nine\":9]\n"
            "    let words = numbers.split(separator: \" \").map(String.init)\n"
            "    return words.sorted { (order[$0] ?? 0) < (order[$1] ?? 0) }.joined(separator: \" \")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/21",
        "language": "swift",
        "entry_point": "findClosestElements",
        "prompt": (
            "// From a sorted array, return the two closest elements as a tuple (smaller, larger).\n"
            "func findClosestElements(numbers: [Double]) -> (Double, Double) {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "let r = findClosestElements(numbers: [1.0, 2.0, 3.0, 4.0, 5.0, 2.2])\n"
            "assert(r == (2.0, 2.2))\n"
            "let r2 = findClosestElements(numbers: [1.0, 2.0, 3.0, 4.0, 5.0, 2.0])\n"
            "assert(r2 == (2.0, 2.0))\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func findClosestElements(numbers: [Double]) -> (Double, Double) {\n"
            "    var best = (numbers[0], numbers[1])\n"
            "    var bestDiff = abs(numbers[1] - numbers[0])\n"
            "    for i in 0..<numbers.count {\n"
            "        for j in (i+1)..<numbers.count {\n"
            "            let d = abs(numbers[i] - numbers[j])\n"
            "            if d < bestDiff { bestDiff = d; best = (min(numbers[i],numbers[j]), max(numbers[i],numbers[j])) }\n"
            "        }\n"
            "    }\n"
            "    return best\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/22",
        "language": "swift",
        "entry_point": "rescaleToUnit",
        "prompt": (
            "// Rescale the array to span [0, 1].\n"
            "func rescaleToUnit(numbers: [Double]) -> [Double] {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "let r = rescaleToUnit(numbers: [1.0, 2.0, 3.0, 4.0, 5.0])\n"
            "assert(r == [0.0, 0.25, 0.5, 0.75, 1.0])\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func rescaleToUnit(numbers: [Double]) -> [Double] {\n"
            "    let mn = numbers.min()!, mx = numbers.max()!\n"
            "    let span = mx - mn\n"
            "    return numbers.map { (span == 0) ? 0.0 : ($0 - mn) / span }\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/23",
        "language": "swift",
        "entry_point": "filterIntegers",
        "prompt": (
            "// Return only the integer values from the Any array.\n"
            "func filterIntegers(values: [Any]) -> [Int] {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "let vals: [Any] = [1, \"a\", 2, 3.5, 4]\n"
            "assert(filterIntegers(values: vals) == [1, 2, 4])\n"
            "assert(filterIntegers(values: []) == [])\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func filterIntegers(values: [Any]) -> [Int] {\n"
            "    return values.compactMap { $0 as? Int }\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/24",
        "language": "swift",
        "entry_point": "strlen",
        "prompt": (
            "// Return the length of `string`.\n"
            "func strlen(string: String) -> Int {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(strlen(string: \"\") == 0)\n"
            "assert(strlen(string: \"hello\") == 5)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func strlen(string: String) -> Int {\n"
            "    return string.count\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/25",
        "language": "swift",
        "entry_point": "largestDivisor",
        "prompt": (
            "// Return the largest divisor of n less than n.\n"
            "func largestDivisor(n: Int) -> Int {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(largestDivisor(n: 15) == 5)\n"
            "assert(largestDivisor(n: 27) == 9)\n"
            "assert(largestDivisor(n: 100) == 50)\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func largestDivisor(n: Int) -> Int {\n"
            "    for i in stride(from: n-1, through: 1, by: -1) { if n % i == 0 { return i } }\n"
            "    return 1\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/swift/26",
        "language": "swift",
        "entry_point": "factorize",
        "prompt": (
            "// Return the prime factorization of n (sorted, with repetitions).\n"
            "func factorize(n: Int) -> [Int] {\n"
            "    // your code here\n"
            "}\n"
        ),
        "test": (
            "assert(factorize(n: 8) == [2, 2, 2])\n"
            "assert(factorize(n: 25) == [5, 5])\n"
            "assert(factorize(n: 70) == [2, 5, 7])\n"
            "print(\"PASS\")\n"
        ),
        "canonical_solution": (
            "func factorize(n: Int) -> [Int] {\n"
            "    var n = n, factors: [Int] = [], d = 2\n"
            "    while d * d <= n { while n % d == 0 { factors.append(d); n /= d }; d += 1 }\n"
            "    if n > 1 { factors.append(n) }\n"
            "    return factors\n"
            "}\n"
        ),
    },
]


_SCALA_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/scala/0",
        "language": "scala",
        "entry_point": "hasCloseElements",
        "prompt": (
            "// Return true if any two numbers are closer than threshold.\n"
            "object Main extends App {\n"
            "  def hasCloseElements(numbers: List[Double], threshold: Double): Boolean = {\n"
            "    // your code here\n"
            "    false\n"
            "  }\n"
        ),
        "test": (
            "  assert(hasCloseElements(List(1.0, 2.0, 3.9, 4.0, 5.0, 2.2), 0.3) == true)\n"
            "  assert(hasCloseElements(List(1.0, 2.0, 3.9, 4.0, 5.0, 2.2), 0.05) == false)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def hasCloseElements(numbers: List[Double], threshold: Double): Boolean =\n"
            "    numbers.indices.exists(i => numbers.indices.exists(j => i != j && math.abs(numbers(i) - numbers(j)) < threshold))\n"
            "  assert(hasCloseElements(List(1.0, 2.0, 3.9, 4.0, 5.0, 2.2), 0.3) == true)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/2",
        "language": "scala",
        "entry_point": "truncateNumber",
        "prompt": (
            "// Return the fractional part of number.\n"
            "object Main extends App {\n"
            "  def truncateNumber(number: Double): Double = {\n"
            "    // your code here\n"
            "    0.0\n"
            "  }\n"
        ),
        "test": (
            "  assert(truncateNumber(3.5) == 0.5)\n"
            "  assert(truncateNumber(1.25) == 0.25)\n"
            "  assert(truncateNumber(123.0) == 0.0)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def truncateNumber(number: Double): Double = number % 1.0\n"
            "  assert(truncateNumber(3.5) == 0.5)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/3",
        "language": "scala",
        "entry_point": "belowZero",
        "prompt": (
            "// Return true if the running balance ever goes below zero.\n"
            "object Main extends App {\n"
            "  def belowZero(operations: List[Int]): Boolean = {\n"
            "    // your code here\n"
            "    false\n"
            "  }\n"
        ),
        "test": (
            "  assert(belowZero(List(1, 2, 3)) == false)\n"
            "  assert(belowZero(List(1, 2, -4, 5)) == true)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def belowZero(operations: List[Int]): Boolean =\n"
            "    operations.scanLeft(0)(_ + _).tail.exists(_ < 0)\n"
            "  assert(belowZero(List(1, 2, -4, 5)) == true)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/4",
        "language": "scala",
        "entry_point": "meanAbsoluteDeviation",
        "prompt": (
            "// Return the mean absolute deviation of the list.\n"
            "object Main extends App {\n"
            "  def meanAbsoluteDeviation(numbers: List[Double]): Double = {\n"
            "    // your code here\n"
            "    0.0\n"
            "  }\n"
        ),
        "test": (
            "  assert(math.abs(meanAbsoluteDeviation(List(1.0, 2.0, 3.0)) - 0.6667) < 0.001)\n"
            "  assert(math.abs(meanAbsoluteDeviation(List(1.0, 2.0, 3.0, 4.0)) - 1.0) < 0.001)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def meanAbsoluteDeviation(numbers: List[Double]): Double = {\n"
            "    val mean = numbers.sum / numbers.length\n"
            "    numbers.map(x => math.abs(x - mean)).sum / numbers.length\n"
            "  }\n"
            "  assert(math.abs(meanAbsoluteDeviation(List(1.0, 2.0, 3.0)) - 0.6667) < 0.001)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/6",
        "language": "scala",
        "entry_point": "parseNestedParens",
        "prompt": (
            "// For each space-separated group of parentheses, return the max nesting depth.\n"
            "object Main extends App {\n"
            "  def parseNestedParens(parenString: String): List[Int] = {\n"
            "    // your code here\n"
            "    List()\n"
            "  }\n"
        ),
        "test": (
            "  assert(parseNestedParens(\"(()()) ((())) () ((())(()))\") == List(2, 3, 1, 3))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def parseNestedParens(parenString: String): List[Int] =\n"
            "    parenString.split(\" \").toList.map { g =>\n"
            "      var d = 0; var m = 0\n"
            "      g.foreach { c => if (c == '(') { d += 1; if (d > m) m = d } else d -= 1 }; m\n"
            "    }\n"
            "  assert(parseNestedParens(\"(()()) ((())) () ((())(()))\") == List(2, 3, 1, 3))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/7",
        "language": "scala",
        "entry_point": "filterBySubstring",
        "prompt": (
            "// Return only the strings that contain substring.\n"
            "object Main extends App {\n"
            "  def filterBySubstring(strings: List[String], substring: String): List[String] = {\n"
            "    // your code here\n"
            "    List()\n"
            "  }\n"
        ),
        "test": (
            "  assert(filterBySubstring(List(\"abc\", \"bacd\", \"cde\", \"array\"), \"a\") == List(\"abc\", \"bacd\", \"array\"))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def filterBySubstring(strings: List[String], substring: String): List[String] =\n"
            "    strings.filter(_.contains(substring))\n"
            "  assert(filterBySubstring(List(\"abc\", \"bacd\", \"cde\", \"array\"), \"a\") == List(\"abc\", \"bacd\", \"array\"))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/8",
        "language": "scala",
        "entry_point": "sumProduct",
        "prompt": (
            "// Return a tuple of (sum, product) of the integers.\n"
            "object Main extends App {\n"
            "  def sumProduct(numbers: List[Int]): (Int, Int) = {\n"
            "    // your code here\n"
            "    (0, 1)\n"
            "  }\n"
        ),
        "test": (
            "  assert(sumProduct(List()) == (0, 1))\n"
            "  assert(sumProduct(List(1, 2, 3, 4)) == (10, 24))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def sumProduct(numbers: List[Int]): (Int, Int) = (numbers.sum, numbers.product)\n"
            "  assert(sumProduct(List(1, 2, 3, 4)) == (10, 24))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/10",
        "language": "scala",
        "entry_point": "isPalindrome",
        "prompt": (
            "// Return true if string is a palindrome.\n"
            "object Main extends App {\n"
            "  def isPalindrome(s: String): Boolean = {\n"
            "    // your code here\n"
            "    false\n"
            "  }\n"
        ),
        "test": (
            "  assert(isPalindrome(\"\") == true)\n"
            "  assert(isPalindrome(\"aba\") == true)\n"
            "  assert(isPalindrome(\"ab\") == false)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def isPalindrome(s: String): Boolean = s == s.reverse\n"
            "  assert(isPalindrome(\"aba\") == true)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/14",
        "language": "scala",
        "entry_point": "greatestCommonDivisor",
        "prompt": (
            "// Return the GCD of two integers.\n"
            "object Main extends App {\n"
            "  def greatestCommonDivisor(a: Int, b: Int): Int = {\n"
            "    // your code here\n"
            "    0\n"
            "  }\n"
        ),
        "test": (
            "  assert(greatestCommonDivisor(3, 7) == 1)\n"
            "  assert(greatestCommonDivisor(10, 15) == 5)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def greatestCommonDivisor(a: Int, b: Int): Int = if (b == 0) a else greatestCommonDivisor(b, a % b)\n"
            "  assert(greatestCommonDivisor(10, 15) == 5)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/15",
        "language": "scala",
        "entry_point": "allPrefixes",
        "prompt": (
            "// Return all prefixes of string from shortest to longest.\n"
            "object Main extends App {\n"
            "  def allPrefixes(s: String): List[String] = {\n"
            "    // your code here\n"
            "    List()\n"
            "  }\n"
        ),
        "test": (
            "  assert(allPrefixes(\"abc\") == List(\"a\", \"ab\", \"abc\"))\n"
            "  assert(allPrefixes(\"\") == List())\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def allPrefixes(s: String): List[String] = (1 to s.length).map(s.take).toList\n"
            "  assert(allPrefixes(\"abc\") == List(\"a\", \"ab\", \"abc\"))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/16",
        "language": "scala",
        "entry_point": "stringSequence",
        "prompt": (
            "// Return space-separated string \"0 1 2 ... n\".\n"
            "object Main extends App {\n"
            "  def stringSequence(n: Int): String = {\n"
            "    // your code here\n"
            "    \"\"\n"
            "  }\n"
        ),
        "test": (
            "  assert(stringSequence(0) == \"0\")\n"
            "  assert(stringSequence(5) == \"0 1 2 3 4 5\")\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def stringSequence(n: Int): String = (0 to n).mkString(\" \")\n"
            "  assert(stringSequence(5) == \"0 1 2 3 4 5\")\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/17",
        "language": "scala",
        "entry_point": "countDistinctCharacters",
        "prompt": (
            "// Return the number of distinct characters (case-insensitive).\n"
            "object Main extends App {\n"
            "  def countDistinctCharacters(s: String): Int = {\n"
            "    // your code here\n"
            "    0\n"
            "  }\n"
        ),
        "test": (
            "  assert(countDistinctCharacters(\"xyzXYZ\") == 3)\n"
            "  assert(countDistinctCharacters(\"Jerry\") == 4)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def countDistinctCharacters(s: String): Int = s.toLowerCase.toSet.size\n"
            "  assert(countDistinctCharacters(\"xyzXYZ\") == 3)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/19",
        "language": "scala",
        "entry_point": "howManyTimes",
        "prompt": (
            "// Count overlapping occurrences of substring in string.\n"
            "object Main extends App {\n"
            "  def howManyTimes(s: String, sub: String): Int = {\n"
            "    // your code here\n"
            "    0\n"
            "  }\n"
        ),
        "test": (
            "  assert(howManyTimes(\"aaa\", \"a\") == 3)\n"
            "  assert(howManyTimes(\"aaa\", \"aa\") == 2)\n"
            "  assert(howManyTimes(\"\", \"a\") == 0)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def howManyTimes(s: String, sub: String): Int =\n"
            "    if (sub.isEmpty) 0 else (0 to s.length - sub.length).count(i => s.startsWith(sub, i))\n"
            "  assert(howManyTimes(\"aaa\", \"aa\") == 2)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/20",
        "language": "scala",
        "entry_point": "sortNumbers",
        "prompt": (
            "// Sort a space-separated string of number words (zero..nine).\n"
            "object Main extends App {\n"
            "  def sortNumbers(numbers: String): String = {\n"
            "    // your code here\n"
            "    \"\"\n"
            "  }\n"
        ),
        "test": (
            "  assert(sortNumbers(\"three one five\") == \"one three five\")\n"
            "  assert(sortNumbers(\"\") == \"\")\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def sortNumbers(numbers: String): String = {\n"
            "    val order = Map(\"zero\"->0,\"one\"->1,\"two\"->2,\"three\"->3,\"four\"->4,\"five\"->5,\"six\"->6,\"seven\"->7,\"eight\"->8,\"nine\"->9)\n"
            "    numbers.split(\" \").filter(_.nonEmpty).sortBy(order).mkString(\" \")\n"
            "  }\n"
            "  assert(sortNumbers(\"three one five\") == \"one three five\")\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/21",
        "language": "scala",
        "entry_point": "findClosestElements",
        "prompt": (
            "// Return the two closest numbers as a tuple (smaller, larger).\n"
            "object Main extends App {\n"
            "  def findClosestElements(numbers: List[Double]): (Double, Double) = {\n"
            "    // your code here\n"
            "    (0.0, 0.0)\n"
            "  }\n"
        ),
        "test": (
            "  assert(findClosestElements(List(1.0, 2.0, 3.0, 4.0, 5.0, 2.2)) == (2.0, 2.2))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def findClosestElements(numbers: List[Double]): (Double, Double) = {\n"
            "    val pairs = for (i <- numbers.indices; j <- (i+1) until numbers.length) yield (numbers(i), numbers(j))\n"
            "    val best = pairs.minBy { case (a,b) => math.abs(a-b) }\n"
            "    (math.min(best._1,best._2), math.max(best._1,best._2))\n"
            "  }\n"
            "  assert(findClosestElements(List(1.0, 2.0, 3.0, 4.0, 5.0, 2.2)) == (2.0, 2.2))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/22",
        "language": "scala",
        "entry_point": "rescaleToUnit",
        "prompt": (
            "// Rescale the list to span [0, 1].\n"
            "object Main extends App {\n"
            "  def rescaleToUnit(numbers: List[Double]): List[Double] = {\n"
            "    // your code here\n"
            "    List()\n"
            "  }\n"
        ),
        "test": (
            "  assert(rescaleToUnit(List(1.0, 2.0, 3.0, 4.0, 5.0)) == List(0.0, 0.25, 0.5, 0.75, 1.0))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def rescaleToUnit(numbers: List[Double]): List[Double] = {\n"
            "    val mn = numbers.min; val mx = numbers.max; val span = mx - mn\n"
            "    numbers.map(x => if (span == 0) 0.0 else (x - mn) / span)\n"
            "  }\n"
            "  assert(rescaleToUnit(List(1.0, 2.0, 3.0, 4.0, 5.0)) == List(0.0, 0.25, 0.5, 0.75, 1.0))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/23",
        "language": "scala",
        "entry_point": "filterIntegers",
        "prompt": (
            "// Return only the integer values from the Any list.\n"
            "object Main extends App {\n"
            "  def filterIntegers(values: List[Any]): List[Int] = {\n"
            "    // your code here\n"
            "    List()\n"
            "  }\n"
        ),
        "test": (
            "  assert(filterIntegers(List(1, \"a\", 2, 3.5, 4)) == List(1, 2, 4))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def filterIntegers(values: List[Any]): List[Int] = values.collect { case i: Int => i }\n"
            "  assert(filterIntegers(List(1, \"a\", 2, 3.5, 4)) == List(1, 2, 4))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/24",
        "language": "scala",
        "entry_point": "strlen",
        "prompt": (
            "// Return the length of string.\n"
            "object Main extends App {\n"
            "  def strlen(s: String): Int = {\n"
            "    // your code here\n"
            "    0\n"
            "  }\n"
        ),
        "test": (
            "  assert(strlen(\"\") == 0)\n"
            "  assert(strlen(\"hello\") == 5)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def strlen(s: String): Int = s.length\n"
            "  assert(strlen(\"hello\") == 5)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/25",
        "language": "scala",
        "entry_point": "largestDivisor",
        "prompt": (
            "// Return the largest divisor of n less than n.\n"
            "object Main extends App {\n"
            "  def largestDivisor(n: Int): Int = {\n"
            "    // your code here\n"
            "    1\n"
            "  }\n"
        ),
        "test": (
            "  assert(largestDivisor(15) == 5)\n"
            "  assert(largestDivisor(27) == 9)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def largestDivisor(n: Int): Int = (n-1 to 1 by -1).find(n % _ == 0).getOrElse(1)\n"
            "  assert(largestDivisor(15) == 5)\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/scala/26",
        "language": "scala",
        "entry_point": "factorize",
        "prompt": (
            "// Return the prime factorization of n (sorted, with repetitions).\n"
            "object Main extends App {\n"
            "  def factorize(n: Int): List[Int] = {\n"
            "    // your code here\n"
            "    List()\n"
            "  }\n"
        ),
        "test": (
            "  assert(factorize(8) == List(2, 2, 2))\n"
            "  assert(factorize(25) == List(5, 5))\n"
            "  assert(factorize(70) == List(2, 5, 7))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
        "canonical_solution": (
            "object Main extends App {\n"
            "  def factorize(n: Int): List[Int] = {\n"
            "    var n2 = n; var factors = List[Int](); var d = 2\n"
            "    while (d * d <= n2) { while (n2 % d == 0) { factors :+= d; n2 /= d }; d += 1 }\n"
            "    if (n2 > 1) factors :+= n2; factors\n"
            "  }\n"
            "  assert(factorize(8) == List(2, 2, 2))\n"
            "  println(\"PASS\")\n"
            "}\n"
        ),
    },
]


_PERL_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/perl/0",
        "language": "perl",
        "entry_point": "has_close_elements",
        "prompt": (
            "# Return 1 if any two numbers in @numbers are closer than $threshold.\n"
            "sub has_close_elements {\n"
            "    my ($numbers_ref, $threshold) = @_;\n"
            "    my @numbers = @$numbers_ref;\n"
            "    # your code here\n"
            "    return 0;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless has_close_elements([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], 0.3) == 1;\n"
            "die \"FAIL 2\\n\" unless has_close_elements([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], 0.05) == 0;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub has_close_elements {\n"
            "    my ($numbers_ref, $threshold) = @_;\n"
            "    my @n = @$numbers_ref;\n"
            "    for my $i (0..$#n) {\n"
            "        for my $j ($i+1..$#n) {\n"
            "            return 1 if abs($n[$i] - $n[$j]) < $threshold;\n"
            "        }\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/2",
        "language": "perl",
        "entry_point": "truncate_number",
        "prompt": (
            "# Return the fractional part of $number.\n"
            "sub truncate_number {\n"
            "    my ($number) = @_;\n"
            "    # your code here\n"
            "    return 0;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless truncate_number(3.5) == 0.5;\n"
            "die \"FAIL 2\\n\" unless truncate_number(1.25) == 0.25;\n"
            "die \"FAIL 3\\n\" unless truncate_number(123.0) == 0.0;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub truncate_number {\n"
            "    my ($number) = @_;\n"
            "    return $number - int($number);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/3",
        "language": "perl",
        "entry_point": "below_zero",
        "prompt": (
            "# Return 1 if the running balance ever goes below zero.\n"
            "sub below_zero {\n"
            "    my ($ops_ref) = @_;\n"
            "    my @ops = @$ops_ref;\n"
            "    # your code here\n"
            "    return 0;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless below_zero([1, 2, 3]) == 0;\n"
            "die \"FAIL 2\\n\" unless below_zero([1, 2, -4, 5]) == 1;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub below_zero {\n"
            "    my ($ops_ref) = @_;\n"
            "    my $bal = 0;\n"
            "    for my $op (@$ops_ref) { $bal += $op; return 1 if $bal < 0; }\n"
            "    return 0;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/4",
        "language": "perl",
        "entry_point": "mean_absolute_deviation",
        "prompt": (
            "# Return the mean absolute deviation of @numbers.\n"
            "sub mean_absolute_deviation {\n"
            "    my ($nums_ref) = @_;\n"
            "    my @nums = @$nums_ref;\n"
            "    # your code here\n"
            "    return 0;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless abs(mean_absolute_deviation([1,2,3]) - 0.6667) < 0.001;\n"
            "die \"FAIL 2\\n\" unless abs(mean_absolute_deviation([1,2,3,4]) - 1.0) < 0.001;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub mean_absolute_deviation {\n"
            "    my ($nums_ref) = @_;\n"
            "    my @nums = @$nums_ref;\n"
            "    my $n = scalar @nums;\n"
            "    my $mean = 0; $mean += $_ for @nums; $mean /= $n;\n"
            "    my $mad = 0; $mad += abs($_ - $mean) for @nums;\n"
            "    return $mad / $n;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/6",
        "language": "perl",
        "entry_point": "parse_nested_parens",
        "prompt": (
            "# For each space-separated group, return max nesting depth.\n"
            "sub parse_nested_parens {\n"
            "    my ($paren_string) = @_;\n"
            "    # your code here\n"
            "    return [];\n"
            "}\n"
        ),
        "test": (
            "my $r = parse_nested_parens(\"(()()) ((())) () ((())(()))\");\n"
            "die \"FAIL\\n\" unless join(',',@$r) eq '2,3,1,3';\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub parse_nested_parens {\n"
            "    my ($str) = @_;\n"
            "    my @result;\n"
            "    for my $group (split / /, $str) {\n"
            "        my ($d, $m) = (0, 0);\n"
            "        for my $c (split //, $group) {\n"
            "            if ($c eq '(') { $d++; $m = $d if $d > $m; } else { $d--; }\n"
            "        }\n"
            "        push @result, $m;\n"
            "    }\n"
            "    return \\@result;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/7",
        "language": "perl",
        "entry_point": "filter_by_substring",
        "prompt": (
            "# Return only strings that contain $substring.\n"
            "sub filter_by_substring {\n"
            "    my ($strings_ref, $substring) = @_;\n"
            "    # your code here\n"
            "    return [];\n"
            "}\n"
        ),
        "test": (
            "my $r = filter_by_substring([\"abc\", \"bacd\", \"cde\", \"array\"], \"a\");\n"
            "die \"FAIL\\n\" unless join(',',@$r) eq 'abc,bacd,array';\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub filter_by_substring {\n"
            "    my ($strings_ref, $sub) = @_;\n"
            "    return [grep { index($_, $sub) >= 0 } @$strings_ref];\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/8",
        "language": "perl",
        "entry_point": "sum_product",
        "prompt": (
            "# Return (sum, product) of @numbers.\n"
            "sub sum_product {\n"
            "    my ($nums_ref) = @_;\n"
            "    # your code here\n"
            "    return (0, 1);\n"
            "}\n"
        ),
        "test": (
            "my ($s, $p) = sum_product([]);\n"
            "die \"FAIL 1\\n\" unless $s == 0 && $p == 1;\n"
            "($s, $p) = sum_product([1, 2, 3, 4]);\n"
            "die \"FAIL 2\\n\" unless $s == 10 && $p == 24;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub sum_product {\n"
            "    my ($nums_ref) = @_;\n"
            "    my ($s, $p) = (0, 1);\n"
            "    $s += $_ for @$nums_ref;\n"
            "    $p *= $_ for @$nums_ref;\n"
            "    return ($s, $p);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/10",
        "language": "perl",
        "entry_point": "is_palindrome",
        "prompt": (
            "# Return 1 if $string is a palindrome.\n"
            "sub is_palindrome {\n"
            "    my ($string) = @_;\n"
            "    # your code here\n"
            "    return 0;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless is_palindrome(\"\") == 1;\n"
            "die \"FAIL 2\\n\" unless is_palindrome(\"aba\") == 1;\n"
            "die \"FAIL 3\\n\" unless is_palindrome(\"ab\") == 0;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub is_palindrome {\n"
            "    my ($s) = @_;\n"
            "    return $s eq reverse($s) ? 1 : 0;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/14",
        "language": "perl",
        "entry_point": "greatest_common_divisor",
        "prompt": (
            "# Return the GCD of $a and $b.\n"
            "sub greatest_common_divisor {\n"
            "    my ($a, $b) = @_;\n"
            "    # your code here\n"
            "    return 0;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless greatest_common_divisor(3, 7) == 1;\n"
            "die \"FAIL 2\\n\" unless greatest_common_divisor(10, 15) == 5;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub greatest_common_divisor {\n"
            "    my ($a, $b) = @_;\n"
            "    while ($b) { ($a, $b) = ($b, $a % $b); }\n"
            "    return $a;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/15",
        "language": "perl",
        "entry_point": "all_prefixes",
        "prompt": (
            "# Return all prefixes of $string from shortest to longest.\n"
            "sub all_prefixes {\n"
            "    my ($string) = @_;\n"
            "    # your code here\n"
            "    return [];\n"
            "}\n"
        ),
        "test": (
            "my $r = all_prefixes(\"abc\");\n"
            "die \"FAIL\\n\" unless join(',',@$r) eq 'a,ab,abc';\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub all_prefixes {\n"
            "    my ($s) = @_;\n"
            "    return [map { substr($s, 0, $_) } 1..length($s)];\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/16",
        "language": "perl",
        "entry_point": "string_sequence",
        "prompt": (
            "# Return space-separated string '0 1 2 ... n'.\n"
            "sub string_sequence {\n"
            "    my ($n) = @_;\n"
            "    # your code here\n"
            "    return '';\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless string_sequence(0) eq '0';\n"
            "die \"FAIL 2\\n\" unless string_sequence(5) eq '0 1 2 3 4 5';\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub string_sequence {\n"
            "    my ($n) = @_;\n"
            "    return join(' ', 0..$n);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/17",
        "language": "perl",
        "entry_point": "count_distinct_characters",
        "prompt": (
            "# Return the number of distinct characters (case-insensitive).\n"
            "sub count_distinct_characters {\n"
            "    my ($string) = @_;\n"
            "    # your code here\n"
            "    return 0;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless count_distinct_characters('xyzXYZ') == 3;\n"
            "die \"FAIL 2\\n\" unless count_distinct_characters('Jerry') == 4;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub count_distinct_characters {\n"
            "    my ($s) = @_;\n"
            "    my %seen;\n"
            "    $seen{$_}++ for split(//, lc($s));\n"
            "    return scalar keys %seen;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/19",
        "language": "perl",
        "entry_point": "how_many_times",
        "prompt": (
            "# Count overlapping occurrences of $substring in $string.\n"
            "sub how_many_times {\n"
            "    my ($string, $substring) = @_;\n"
            "    # your code here\n"
            "    return 0;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless how_many_times('aaa', 'a') == 3;\n"
            "die \"FAIL 2\\n\" unless how_many_times('aaa', 'aa') == 2;\n"
            "die \"FAIL 3\\n\" unless how_many_times('', 'a') == 0;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub how_many_times {\n"
            "    my ($s, $sub) = @_;\n"
            "    return 0 unless length($sub);\n"
            "    my $count = 0;\n"
            "    my $pos = 0;\n"
            "    while (($pos = index($s, $sub, $pos)) != -1) { $count++; $pos++; }\n"
            "    return $count;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/20",
        "language": "perl",
        "entry_point": "sort_numbers",
        "prompt": (
            "# Sort a space-separated string of number words (zero..nine).\n"
            "sub sort_numbers {\n"
            "    my ($numbers) = @_;\n"
            "    # your code here\n"
            "    return '';\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless sort_numbers('three one five') eq 'one three five';\n"
            "die \"FAIL 2\\n\" unless sort_numbers('') eq '';\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub sort_numbers {\n"
            "    my ($numbers) = @_;\n"
            "    my %order = (zero=>0,one=>1,two=>2,three=>3,four=>4,five=>5,six=>6,seven=>7,eight=>8,nine=>9);\n"
            "    my @words = grep { $_ ne '' } split(/ /, $numbers);\n"
            "    return join(' ', sort { $order{$a} <=> $order{$b} } @words);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/21",
        "language": "perl",
        "entry_point": "find_closest_elements",
        "prompt": (
            "# Return the two closest numbers as (smaller, larger).\n"
            "sub find_closest_elements {\n"
            "    my ($numbers_ref) = @_;\n"
            "    # your code here\n"
            "    return (0, 0);\n"
            "}\n"
        ),
        "test": (
            "my ($a, $b) = find_closest_elements([1.0, 2.0, 3.0, 4.0, 5.0, 2.2]);\n"
            "die \"FAIL\\n\" unless $a == 2.0 && $b == 2.2;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub find_closest_elements {\n"
            "    my ($nums) = @_;\n"
            "    my ($best_a, $best_b, $best_d) = ($nums->[0], $nums->[1], abs($nums->[1]-$nums->[0]));\n"
            "    for my $i (0..$#$nums) {\n"
            "        for my $j ($i+1..$#$nums) {\n"
            "            my $d = abs($nums->[$i]-$nums->[$j]);\n"
            "            if ($d < $best_d) { $best_d=$d; $best_a=$nums->[$i]; $best_b=$nums->[$j]; }\n"
            "        }\n"
            "    }\n"
            "    return ($best_a < $best_b) ? ($best_a,$best_b) : ($best_b,$best_a);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/22",
        "language": "perl",
        "entry_point": "rescale_to_unit",
        "prompt": (
            "# Rescale the array to span [0, 1].\n"
            "sub rescale_to_unit {\n"
            "    my ($nums_ref) = @_;\n"
            "    # your code here\n"
            "    return [];\n"
            "}\n"
        ),
        "test": (
            "my $r = rescale_to_unit([1.0, 2.0, 3.0, 4.0, 5.0]);\n"
            "die \"FAIL\\n\" unless join(',',@$r) eq '0,0.25,0.5,0.75,1';\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub rescale_to_unit {\n"
            "    my ($nums) = @_;\n"
            "    my ($mn, $mx) = ($nums->[0], $nums->[0]);\n"
            "    for (@$nums) { $mn = $_ if $_ < $mn; $mx = $_ if $_ > $mx; }\n"
            "    my $span = $mx - $mn;\n"
            "    return [map { $span == 0 ? 0 : ($_ - $mn) / $span } @$nums];\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/23",
        "language": "perl",
        "entry_point": "filter_integers",
        "prompt": (
            "# Return only the integer values from @values.\n"
            "sub filter_integers {\n"
            "    my ($vals_ref) = @_;\n"
            "    # your code here\n"
            "    return [];\n"
            "}\n"
        ),
        "test": (
            "my $r = filter_integers([1, 'a', 2, 3.5, 4]);\n"
            "die \"FAIL\\n\" unless join(',',@$r) eq '1,2,4';\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub filter_integers {\n"
            "    my ($vals) = @_;\n"
            "    return [grep { /^-?\\d+$/ } @$vals];\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/24",
        "language": "perl",
        "entry_point": "strlen",
        "prompt": (
            "# Return the length of $string.\n"
            "sub strlen {\n"
            "    my ($string) = @_;\n"
            "    # your code here\n"
            "    return 0;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless strlen('') == 0;\n"
            "die \"FAIL 2\\n\" unless strlen('hello') == 5;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub strlen {\n"
            "    my ($s) = @_;\n"
            "    return length($s);\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/25",
        "language": "perl",
        "entry_point": "largest_divisor",
        "prompt": (
            "# Return the largest divisor of n less than n.\n"
            "sub largest_divisor {\n"
            "    my ($n) = @_;\n"
            "    # your code here\n"
            "    return 1;\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless largest_divisor(15) == 5;\n"
            "die \"FAIL 2\\n\" unless largest_divisor(27) == 9;\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub largest_divisor {\n"
            "    my ($n) = @_;\n"
            "    for my $i (reverse 1..$n-1) { return $i if $n % $i == 0; }\n"
            "    return 1;\n"
            "}\n"
        ),
    },
    {
        "task_id": "MultiPL-E/perl/26",
        "language": "perl",
        "entry_point": "factorize",
        "prompt": (
            "# Return the prime factorization of n (sorted, with repetitions).\n"
            "sub factorize {\n"
            "    my ($n) = @_;\n"
            "    # your code here\n"
            "    return [];\n"
            "}\n"
        ),
        "test": (
            "die \"FAIL 1\\n\" unless join(',', @{factorize(8)}) eq '2,2,2';\n"
            "die \"FAIL 2\\n\" unless join(',', @{factorize(25)}) eq '5,5';\n"
            "die \"FAIL 3\\n\" unless join(',', @{factorize(70)}) eq '2,5,7';\n"
            "print \"PASS\\n\";\n"
        ),
        "canonical_solution": (
            "sub factorize {\n"
            "    my ($n) = @_;\n"
            "    my @factors; my $d = 2;\n"
            "    while ($d * $d <= $n) { while ($n % $d == 0) { push @factors, $d; $n /= $d; } $d++; }\n"
            "    push @factors, $n if $n > 1;\n"
            "    return \\@factors;\n"
            "}\n"
        ),
    },
]


_RACKET_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/racket/0",
        "language": "racket",
        "entry_point": "has-close-elements",
        "prompt": (
            "#lang racket\n"
            "; Return #t if any two numbers in lst are closer than threshold.\n"
            "(define (has-close-elements lst threshold)\n"
            "  ; your code here\n"
            "  #f)\n"
        ),
        "test": (
            "(unless (has-close-elements '(1.0 2.0 3.9 4.0 5.0 2.2) 0.3) (error \"FAIL 1\"))\n"
            "(unless (not (has-close-elements '(1.0 2.0 3.9 4.0 5.0 2.2) 0.05)) (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (has-close-elements lst threshold)\n"
            "  (for*/or ([a lst] [b lst] #:unless (equal? a b))\n"
            "    (< (abs (- a b)) threshold)))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/2",
        "language": "racket",
        "entry_point": "truncate-number",
        "prompt": (
            "#lang racket\n"
            "; Return the fractional part of number.\n"
            "(define (truncate-number number)\n"
            "  ; your code here\n"
            "  0)\n"
        ),
        "test": (
            "(unless (= (truncate-number 3.5) 0.5) (error \"FAIL 1\"))\n"
            "(unless (= (truncate-number 1.25) 0.25) (error \"FAIL 2\"))\n"
            "(unless (= (truncate-number 123.0) 0.0) (error \"FAIL 3\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (truncate-number number) (- number (truncate number)))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/3",
        "language": "racket",
        "entry_point": "below-zero",
        "prompt": (
            "#lang racket\n"
            "; Return #t if the running balance ever goes below zero.\n"
            "(define (below-zero operations)\n"
            "  ; your code here\n"
            "  #f)\n"
        ),
        "test": (
            "(unless (not (below-zero '(1 2 3))) (error \"FAIL 1\"))\n"
            "(unless (below-zero '(1 2 -4 5)) (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (below-zero ops)\n"
            "  (let loop ([ops ops] [bal 0])\n"
            "    (cond [(null? ops) #f]\n"
            "          [(< (+ bal (car ops)) 0) #t]\n"
            "          [else (loop (cdr ops) (+ bal (car ops)))])))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/4",
        "language": "racket",
        "entry_point": "mean-absolute-deviation",
        "prompt": (
            "#lang racket\n"
            "; Return the mean absolute deviation of the list.\n"
            "(define (mean-absolute-deviation numbers)\n"
            "  ; your code here\n"
            "  0)\n"
        ),
        "test": (
            "(unless (< (abs (- (mean-absolute-deviation '(1.0 2.0 3.0)) 0.6667)) 0.001) (error \"FAIL 1\"))\n"
            "(unless (< (abs (- (mean-absolute-deviation '(1.0 2.0 3.0 4.0)) 1.0)) 0.001) (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (mean-absolute-deviation numbers)\n"
            "  (let* ([n (length numbers)]\n"
            "         [mean (/ (apply + numbers) n)])\n"
            "    (/ (apply + (map (lambda (x) (abs (- x mean))) numbers)) n)))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/6",
        "language": "racket",
        "entry_point": "parse-nested-parens",
        "prompt": (
            "#lang racket\n"
            "; For each space-separated group, return the max nesting depth.\n"
            "(define (parse-nested-parens paren-string)\n"
            "  ; your code here\n"
            "  '())\n"
        ),
        "test": (
            "(unless (equal? (parse-nested-parens \"(()()) ((())) () ((())(()))\") '(2 3 1 3)) (error \"FAIL\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (parse-nested-parens paren-string)\n"
            "  (map (lambda (group)\n"
            "         (let loop ([chars (string->list group)] [d 0] [m 0])\n"
            "           (if (null? chars) m\n"
            "               (let ([new-d (if (char=? (car chars) #\\() (+ d 1) (- d 1))])\n"
            "                 (loop (cdr chars) new-d (max m new-d))))))\n"
            "       (string-split paren-string)))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/7",
        "language": "racket",
        "entry_point": "filter-by-substring",
        "prompt": (
            "#lang racket\n"
            "; Return only the strings that contain substring.\n"
            "(define (filter-by-substring strings substring)\n"
            "  ; your code here\n"
            "  '())\n"
        ),
        "test": (
            "(unless (equal? (filter-by-substring '(\"abc\" \"bacd\" \"cde\" \"array\") \"a\") '(\"abc\" \"bacd\" \"array\")) (error \"FAIL\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (filter-by-substring strings substring)\n"
            "  (filter (lambda (s) (string-contains s substring)) strings))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/8",
        "language": "racket",
        "entry_point": "sum-product",
        "prompt": (
            "#lang racket\n"
            "; Return a pair (sum . product) of the numbers.\n"
            "(define (sum-product numbers)\n"
            "  ; your code here\n"
            "  (cons 0 1))\n"
        ),
        "test": (
            "(unless (equal? (sum-product '()) (cons 0 1)) (error \"FAIL 1\"))\n"
            "(unless (equal? (sum-product '(1 2 3 4)) (cons 10 24)) (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (sum-product numbers)\n"
            "  (cons (apply + numbers) (apply * (if (null? numbers) '(1) numbers))))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/10",
        "language": "racket",
        "entry_point": "is-palindrome",
        "prompt": (
            "#lang racket\n"
            "; Return #t if string is a palindrome.\n"
            "(define (is-palindrome s)\n"
            "  ; your code here\n"
            "  #f)\n"
        ),
        "test": (
            "(unless (is-palindrome \"\") (error \"FAIL 1\"))\n"
            "(unless (is-palindrome \"aba\") (error \"FAIL 2\"))\n"
            "(unless (not (is-palindrome \"ab\")) (error \"FAIL 3\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (is-palindrome s)\n"
            "  (equal? s (list->string (reverse (string->list s)))))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/14",
        "language": "racket",
        "entry_point": "greatest-common-divisor",
        "prompt": (
            "#lang racket\n"
            "; Return the GCD of a and b.\n"
            "(define (greatest-common-divisor a b)\n"
            "  ; your code here\n"
            "  0)\n"
        ),
        "test": (
            "(unless (= (greatest-common-divisor 3 7) 1) (error \"FAIL 1\"))\n"
            "(unless (= (greatest-common-divisor 10 15) 5) (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (greatest-common-divisor a b) (if (= b 0) a (greatest-common-divisor b (modulo a b))))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/15",
        "language": "racket",
        "entry_point": "all-prefixes",
        "prompt": (
            "#lang racket\n"
            "; Return all prefixes of string from shortest to longest.\n"
            "(define (all-prefixes s)\n"
            "  ; your code here\n"
            "  '())\n"
        ),
        "test": (
            "(unless (equal? (all-prefixes \"abc\") '(\"a\" \"ab\" \"abc\")) (error \"FAIL\"))\n"
            "(unless (equal? (all-prefixes \"\") '()) (error \"FAIL empty\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (all-prefixes s)\n"
            "  (map (lambda (i) (substring s 0 i)) (range 1 (+ (string-length s) 1))))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/16",
        "language": "racket",
        "entry_point": "string-sequence",
        "prompt": (
            "#lang racket\n"
            "; Return space-separated string '0 1 2 ... n'.\n"
            "(define (string-sequence n)\n"
            "  ; your code here\n"
            "  \"\")\n"
        ),
        "test": (
            "(unless (equal? (string-sequence 0) \"0\") (error \"FAIL 1\"))\n"
            "(unless (equal? (string-sequence 5) \"0 1 2 3 4 5\") (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (string-sequence n)\n"
            "  (string-join (map number->string (range 0 (+ n 1))) \" \"))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/17",
        "language": "racket",
        "entry_point": "count-distinct-characters",
        "prompt": (
            "#lang racket\n"
            "; Return the number of distinct characters (case-insensitive).\n"
            "(define (count-distinct-characters s)\n"
            "  ; your code here\n"
            "  0)\n"
        ),
        "test": (
            "(unless (= (count-distinct-characters \"xyzXYZ\") 3) (error \"FAIL 1\"))\n"
            "(unless (= (count-distinct-characters \"Jerry\") 4) (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (count-distinct-characters s)\n"
            "  (set-count (list->set (string->list (string-downcase s)))))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/19",
        "language": "racket",
        "entry_point": "how-many-times",
        "prompt": (
            "#lang racket\n"
            "; Count overlapping occurrences of substring in string.\n"
            "(define (how-many-times s sub)\n"
            "  ; your code here\n"
            "  0)\n"
        ),
        "test": (
            "(unless (= (how-many-times \"aaa\" \"a\") 3) (error \"FAIL 1\"))\n"
            "(unless (= (how-many-times \"aaa\" \"aa\") 2) (error \"FAIL 2\"))\n"
            "(unless (= (how-many-times \"\" \"a\") 0) (error \"FAIL 3\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (how-many-times s sub)\n"
            "  (if (= (string-length sub) 0) 0\n"
            "      (let loop ([i 0] [count 0])\n"
            "        (if (> (+ i (string-length sub)) (string-length s)) count\n"
            "            (loop (+ i 1)\n"
            "                  (if (equal? (substring s i (+ i (string-length sub))) sub)\n"
            "                      (+ count 1) count))))))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/20",
        "language": "racket",
        "entry_point": "sort-numbers",
        "prompt": (
            "#lang racket\n"
            "; Sort a space-separated string of number words (zero..nine).\n"
            "(define (sort-numbers numbers)\n"
            "  ; your code here\n"
            "  \"\")\n"
        ),
        "test": (
            "(unless (equal? (sort-numbers \"three one five\") \"one three five\") (error \"FAIL 1\"))\n"
            "(unless (equal? (sort-numbers \"\") \"\") (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (sort-numbers numbers)\n"
            "  (define order '((\"zero\" . 0)(\"one\" . 1)(\"two\" . 2)(\"three\" . 3)(\"four\" . 4)(\"five\" . 5)(\"six\" . 6)(\"seven\" . 7)(\"eight\" . 8)(\"nine\" . 9)))\n"
            "  (define words (filter (lambda (w) (not (equal? w \"\"))) (string-split numbers)))\n"
            "  (string-join (sort words (lambda (a b) (< (cdr (assoc a order)) (cdr (assoc b order)))))))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/21",
        "language": "racket",
        "entry_point": "find-closest-elements",
        "prompt": (
            "#lang racket\n"
            "; Return the two closest numbers as a pair (smaller . larger).\n"
            "(define (find-closest-elements numbers)\n"
            "  ; your code here\n"
            "  (cons 0 0))\n"
        ),
        "test": (
            "(let ([r (find-closest-elements '(1.0 2.0 3.0 4.0 5.0 2.2))])\n"
            "  (unless (and (= (car r) 2.0) (= (cdr r) 2.2)) (error \"FAIL\")))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (find-closest-elements numbers)\n"
            "  (let* ([pairs (for*/list ([a numbers] [b numbers] #:unless (= a b)) (cons a b))]\n"
            "         [best (argmin (lambda (p) (abs (- (car p) (cdr p)))) pairs)])\n"
            "    (if (< (car best) (cdr best)) best (cons (cdr best) (car best)))))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/22",
        "language": "racket",
        "entry_point": "rescale-to-unit",
        "prompt": (
            "#lang racket\n"
            "; Rescale the list to span [0, 1].\n"
            "(define (rescale-to-unit numbers)\n"
            "  ; your code here\n"
            "  '())\n"
        ),
        "test": (
            "(unless (equal? (rescale-to-unit '(1.0 2.0 3.0 4.0 5.0)) '(0.0 0.25 0.5 0.75 1.0)) (error \"FAIL\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (rescale-to-unit numbers)\n"
            "  (let* ([mn (apply min numbers)] [mx (apply max numbers)] [span (- mx mn)])\n"
            "    (map (lambda (x) (if (= span 0) 0.0 (/ (- x mn) span))) numbers)))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/23",
        "language": "racket",
        "entry_point": "filter-integers",
        "prompt": (
            "#lang racket\n"
            "; Return only the integer values from the list.\n"
            "(define (filter-integers values)\n"
            "  ; your code here\n"
            "  '())\n"
        ),
        "test": (
            "(unless (equal? (filter-integers '(1 \"a\" 2 3.5 4)) '(1 2 4)) (error \"FAIL\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (filter-integers values) (filter integer? values))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/24",
        "language": "racket",
        "entry_point": "strlen",
        "prompt": (
            "#lang racket\n"
            "; Return the length of string s.\n"
            "(define (strlen s)\n"
            "  ; your code here\n"
            "  0)\n"
        ),
        "test": (
            "(unless (= (strlen \"\") 0) (error \"FAIL 1\"))\n"
            "(unless (= (strlen \"hello\") 5) (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (strlen s) (string-length s))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/25",
        "language": "racket",
        "entry_point": "largest-divisor",
        "prompt": (
            "#lang racket\n"
            "; Return the largest divisor of n less than n.\n"
            "(define (largest-divisor n)\n"
            "  ; your code here\n"
            "  1)\n"
        ),
        "test": (
            "(unless (= (largest-divisor 15) 5) (error \"FAIL 1\"))\n"
            "(unless (= (largest-divisor 27) 9) (error \"FAIL 2\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (largest-divisor n)\n"
            "  (let loop ([i (- n 1)])\n"
            "    (if (= (modulo n i) 0) i (loop (- i 1)))))\n"
        ),
    },
    {
        "task_id": "MultiPL-E/racket/26",
        "language": "racket",
        "entry_point": "factorize",
        "prompt": (
            "#lang racket\n"
            "; Return the prime factorization of n (sorted, with repetitions).\n"
            "(define (factorize n)\n"
            "  ; your code here\n"
            "  '())\n"
        ),
        "test": (
            "(unless (equal? (factorize 8) '(2 2 2)) (error \"FAIL 1\"))\n"
            "(unless (equal? (factorize 25) '(5 5)) (error \"FAIL 2\"))\n"
            "(unless (equal? (factorize 70) '(2 5 7)) (error \"FAIL 3\"))\n"
            "(display \"PASS\") (newline)\n"
        ),
        "canonical_solution": (
            "#lang racket\n"
            "(define (factorize n)\n"
            "  (let loop ([n n] [d 2] [factors '()])\n"
            "    (cond [(> (* d d) n) (if (> n 1) (reverse (cons n factors)) (reverse factors))]\n"
            "          [(= (modulo n d) 0) (loop (/ n d) d (cons d factors))]\n"
            "          [else (loop n (+ d 1) factors)])))\n"
        ),
    },
]


# ── PowerShell Problems ────────────────────────────────────────────────────────
_POWERSHELL_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/powershell/0",
        "language": "powershell",
        "entry_point": "HasCloseElements",
        "prompt": (
            "# Return $true if any two numbers in $numbers are closer than $threshold.\n"
            "function HasCloseElements {\n"
            "    param([double[]]$numbers, [double]$threshold)\n"
            "    # your code here\n"
            "    return $false\n"
            "}\n"
        ),
        "test": (
            "if (-not (HasCloseElements @(1.0, 2.0, 3.9, 4.0, 5.0, 2.2) 0.3)) { throw 'FAIL 1' }\n"
            "if (HasCloseElements @(1.0, 2.0, 3.9, 4.0, 5.0, 2.2) 0.05) { throw 'FAIL 2' }\n"
            "if (-not (HasCloseElements @(1.0, 2.0, 3.4, 4.0, 5.0, 2.2) 0.3)) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/1",
        "language": "powershell",
        "entry_point": "TruncateNumber",
        "prompt": (
            "# Return the fractional part of $number (the part after the decimal point).\n"
            "function TruncateNumber {\n"
            "    param([double]$number)\n"
            "    # your code here\n"
            "    return 0.0\n"
            "}\n"
        ),
        "test": (
            "if ([Math]::Abs((TruncateNumber 3.5) - 0.5) -gt 1e-9) { throw 'FAIL 1' }\n"
            "if ([Math]::Abs((TruncateNumber 1.25) - 0.25) -gt 1e-9) { throw 'FAIL 2' }\n"
            "if ([Math]::Abs((TruncateNumber 123.0) - 0.0) -gt 1e-9) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/2",
        "language": "powershell",
        "entry_point": "BelowZero",
        "prompt": (
            "# Given a list of operations, return $true if the running sum ever goes below zero.\n"
            "function BelowZero {\n"
            "    param([int[]]$operations)\n"
            "    # your code here\n"
            "    return $false\n"
            "}\n"
        ),
        "test": (
            "if (BelowZero @(1,-2,3,4,-3,2,3)) { throw 'FAIL 1' }\n"
            "if (-not (BelowZero @(1,-4,3,4,-3,2,3))) { throw 'FAIL 2' }\n"
            "if (BelowZero @()) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/3",
        "language": "powershell",
        "entry_point": "MeanAbsoluteDeviation",
        "prompt": (
            "# Return the mean absolute deviation of the numbers in $numbers around their mean.\n"
            "function MeanAbsoluteDeviation {\n"
            "    param([double[]]$numbers)\n"
            "    # your code here\n"
            "    return 0.0\n"
            "}\n"
        ),
        "test": (
            "if ([Math]::Abs((MeanAbsoluteDeviation @(1.0,2.0,3.0,4.0)) - 1.0) -gt 1e-6) { throw 'FAIL 1' }\n"
            "if ([Math]::Abs((MeanAbsoluteDeviation @(1.0,2.0,3.0)) - (2.0/3.0)) -gt 1e-6) { throw 'FAIL 2' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/4",
        "language": "powershell",
        "entry_point": "Intersperse",
        "prompt": (
            "# Insert $delimiter between each element of $numbers and return the new array.\n"
            "function Intersperse {\n"
            "    param([int[]]$numbers, [int]$delimiter)\n"
            "    # your code here\n"
            "    return @()\n"
            "}\n"
        ),
        "test": (
            "$r = Intersperse @(1,2,3) 4\n"
            "if ($r.Count -ne 5 -or $r[0] -ne 1 -or $r[1] -ne 4 -or $r[2] -ne 2 -or $r[3] -ne 4 -or $r[4] -ne 3) { throw 'FAIL 1' }\n"
            "$r = Intersperse @(1,2) 0\n"
            "if ($r.Count -ne 3 -or $r[1] -ne 0) { throw 'FAIL 2' }\n"
            "$r = Intersperse @() 9\n"
            "if ($r.Count -ne 0) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/5",
        "language": "powershell",
        "entry_point": "RollingMax",
        "prompt": (
            "# Return an array of running maximums for each prefix of $numbers.\n"
            "function RollingMax {\n"
            "    param([int[]]$numbers)\n"
            "    # your code here\n"
            "    return @()\n"
            "}\n"
        ),
        "test": (
            "$r = RollingMax @(1,2,3,2,3,4,2)\n"
            "if (\"$r\" -ne '1 2 3 3 3 4 4') { throw \"FAIL 1: got $r\" }\n"
            "$r = RollingMax @(3,2,1)\n"
            "if (\"$r\" -ne '3 3 3') { throw \"FAIL 2: got $r\" }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/6",
        "language": "powershell",
        "entry_point": "IsPalindrome",
        "prompt": (
            "# Return $true if the string $text is a palindrome, $false otherwise.\n"
            "function IsPalindrome {\n"
            "    param([string]$text)\n"
            "    # your code here\n"
            "    return $false\n"
            "}\n"
        ),
        "test": (
            "if (-not (IsPalindrome 'racecar')) { throw 'FAIL 1' }\n"
            "if (IsPalindrome 'hello') { throw 'FAIL 2' }\n"
            "if (-not (IsPalindrome '')) { throw 'FAIL 3' }\n"
            "if (-not (IsPalindrome 'a')) { throw 'FAIL 4' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/7",
        "language": "powershell",
        "entry_point": "LargestDivisor",
        "prompt": (
            "# Return the largest integer that divides $n evenly and is smaller than $n.\n"
            "function LargestDivisor {\n"
            "    param([int]$n)\n"
            "    # your code here\n"
            "    return 1\n"
            "}\n"
        ),
        "test": (
            "if ((LargestDivisor 15) -ne 5) { throw 'FAIL 1' }\n"
            "if ((LargestDivisor 27) -ne 9) { throw 'FAIL 2' }\n"
            "if ((LargestDivisor 100) -ne 50) { throw 'FAIL 3' }\n"
            "if ((LargestDivisor 13) -ne 1) { throw 'FAIL 4' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/8",
        "language": "powershell",
        "entry_point": "IsPrime",
        "prompt": (
            "# Return $true if $n is a prime number.\n"
            "function IsPrime {\n"
            "    param([int]$n)\n"
            "    # your code here\n"
            "    return $false\n"
            "}\n"
        ),
        "test": (
            "if (IsPrime 1) { throw 'FAIL 1' }\n"
            "if (-not (IsPrime 2)) { throw 'FAIL 2' }\n"
            "if (-not (IsPrime 7)) { throw 'FAIL 3' }\n"
            "if (IsPrime 9) { throw 'FAIL 4' }\n"
            "if (-not (IsPrime 11)) { throw 'FAIL 5' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/9",
        "language": "powershell",
        "entry_point": "Fib",
        "prompt": (
            "# Return the n-th Fibonacci number (0-indexed: Fib(0)=0, Fib(1)=1).\n"
            "function Fib {\n"
            "    param([int]$n)\n"
            "    # your code here\n"
            "    return 0\n"
            "}\n"
        ),
        "test": (
            "if ((Fib 0) -ne 0) { throw 'FAIL 1' }\n"
            "if ((Fib 1) -ne 1) { throw 'FAIL 2' }\n"
            "if ((Fib 7) -ne 13) { throw 'FAIL 3' }\n"
            "if ((Fib 10) -ne 55) { throw 'FAIL 4' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/10",
        "language": "powershell",
        "entry_point": "FilterBySubstring",
        "prompt": (
            "# Return strings from $strings that contain $substring.\n"
            "function FilterBySubstring {\n"
            "    param([string[]]$strings, [string]$substring)\n"
            "    # your code here\n"
            "    return @()\n"
            "}\n"
        ),
        "test": (
            "$r = FilterBySubstring @('abc','bacd','cde','array') 'a'\n"
            "if ($r.Count -ne 3) { throw \"FAIL 1: got $($r.Count)\" }\n"
            "$r = FilterBySubstring @('hello','world') 'xyz'\n"
            "if ($r.Count -ne 0) { throw 'FAIL 2' }\n"
            "$r = FilterBySubstring @() 'x'\n"
            "if ($r.Count -ne 0) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/11",
        "language": "powershell",
        "entry_point": "HowManyTimes",
        "prompt": (
            "# Count how many times $substring appears in $string (including overlapping).\n"
            "function HowManyTimes {\n"
            "    param([string]$string, [string]$substring)\n"
            "    # your code here\n"
            "    return 0\n"
            "}\n"
        ),
        "test": (
            "if ((HowManyTimes 'aaa' 'aa') -ne 2) { throw 'FAIL 1' }\n"
            "if ((HowManyTimes 'hello' 'l') -ne 2) { throw 'FAIL 2' }\n"
            "if ((HowManyTimes 'abc' 'xyz') -ne 0) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/12",
        "language": "powershell",
        "entry_point": "CountUppercase",
        "prompt": (
            "# Count the number of uppercase letters in $s.\n"
            "function CountUppercase {\n"
            "    param([string]$s)\n"
            "    # your code here\n"
            "    return 0\n"
            "}\n"
        ),
        "test": (
            "if ((CountUppercase 'Hello World') -ne 2) { throw 'FAIL 1' }\n"
            "if ((CountUppercase 'hello') -ne 0) { throw 'FAIL 2' }\n"
            "if ((CountUppercase 'ABC') -ne 3) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/13",
        "language": "powershell",
        "entry_point": "SumSquares",
        "prompt": (
            "# Return the sum of squares of all integers from 1 to $n inclusive.\n"
            "function SumSquares {\n"
            "    param([int]$n)\n"
            "    # your code here\n"
            "    return 0\n"
            "}\n"
        ),
        "test": (
            "if ((SumSquares 1) -ne 1) { throw 'FAIL 1' }\n"
            "if ((SumSquares 3) -ne 14) { throw 'FAIL 2' }\n"
            "if ((SumSquares 5) -ne 55) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/14",
        "language": "powershell",
        "entry_point": "MaxElement",
        "prompt": (
            "# Return the maximum element in $lst.\n"
            "function MaxElement {\n"
            "    param([int[]]$lst)\n"
            "    # your code here\n"
            "    return 0\n"
            "}\n"
        ),
        "test": (
            "if ((MaxElement @(1,2,3)) -ne 3) { throw 'FAIL 1' }\n"
            "if ((MaxElement @(5,3,8,1)) -ne 8) { throw 'FAIL 2' }\n"
            "if ((MaxElement @(-1,-5,-3)) -ne -1) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/15",
        "language": "powershell",
        "entry_point": "Fizzbuzz",
        "prompt": (
            "# Return the number of integers in range [1, $n] that are divisible by 11 or 13.\n"
            "function Fizzbuzz {\n"
            "    param([int]$n)\n"
            "    # your code here\n"
            "    return 0\n"
            "}\n"
        ),
        "test": (
            "if ((Fizzbuzz 50) -ne 6) { throw 'FAIL 1' }\n"
            "if ((Fizzbuzz 78) -ne 11) { throw 'FAIL 2' }\n"
            "if ((Fizzbuzz 79) -ne 11) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/16",
        "language": "powershell",
        "entry_point": "SortDescending",
        "prompt": (
            "# Return a new array with the elements of $lst sorted in descending order.\n"
            "function SortDescending {\n"
            "    param([int[]]$lst)\n"
            "    # your code here\n"
            "    return @()\n"
            "}\n"
        ),
        "test": (
            "$r = SortDescending @(3,1,4,1,5,9)\n"
            "if (\"$r\" -ne '9 5 4 3 1 1') { throw \"FAIL 1: got $r\" }\n"
            "$r = SortDescending @(1)\n"
            "if ($r[0] -ne 1) { throw 'FAIL 2' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/17",
        "language": "powershell",
        "entry_point": "UniqueElements",
        "prompt": (
            "# Return an array of unique elements from $lst, preserving first-occurrence order.\n"
            "function UniqueElements {\n"
            "    param([int[]]$lst)\n"
            "    # your code here\n"
            "    return @()\n"
            "}\n"
        ),
        "test": (
            "$r = UniqueElements @(1,2,3,2,1)\n"
            "if ($r.Count -ne 3 -or $r[0] -ne 1 -or $r[1] -ne 2 -or $r[2] -ne 3) { throw \"FAIL 1: $r\" }\n"
            "$r = UniqueElements @(5,5,5)\n"
            "if ($r.Count -ne 1 -or $r[0] -ne 5) { throw 'FAIL 2' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/18",
        "language": "powershell",
        "entry_point": "Median",
        "prompt": (
            "# Return the median of $lst (assume list is non-empty, sort it first).\n"
            "function Median {\n"
            "    param([double[]]$lst)\n"
            "    # your code here\n"
            "    return 0.0\n"
            "}\n"
        ),
        "test": (
            "if ((Median @(3,1,2)) -ne 2.0) { throw 'FAIL 1' }\n"
            "if ((Median @(3,1,2,4)) -ne 2.5) { throw 'FAIL 2' }\n"
            "if ((Median @(5)) -ne 5.0) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
    {
        "task_id": "MultiPL-E/powershell/19",
        "language": "powershell",
        "entry_point": "CountVowels",
        "prompt": (
            "# Count the number of vowels (a, e, i, o, u, case-insensitive) in $s.\n"
            "function CountVowels {\n"
            "    param([string]$s)\n"
            "    # your code here\n"
            "    return 0\n"
            "}\n"
        ),
        "test": (
            "if ((CountVowels 'hello') -ne 2) { throw 'FAIL 1' }\n"
            "if ((CountVowels 'AEIOUaeiou') -ne 10) { throw 'FAIL 2' }\n"
            "if ((CountVowels 'rhythm') -ne 0) { throw 'FAIL 3' }\n"
            "Write-Output 'PASS'\n"
        ),
    },
]

# ── Python Problems ────────────────────────────────────────────────────────────
_PYTHON_PROBLEMS: list[dict] = [
    {
        "task_id": "MultiPL-E/python/0",
        "language": "python",
        "entry_point": "has_close_elements",
        "prompt": (
            "from typing import List\n\n"
            "def has_close_elements(numbers: List[float], threshold: float) -> bool:\n"
            "    \"\"\" Check if any two numbers in the list are closer than threshold. \"\"\"\n"
            "    # your code here\n"
            "    return False\n"
        ),
        "test": (
            "assert has_close_elements([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], 0.3) == True\n"
            "assert has_close_elements([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], 0.05) == False\n"
            "assert has_close_elements([1.0, 2.0, 3.4, 4.0, 5.0, 2.2], 0.3) == True\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/1",
        "language": "python",
        "entry_point": "truncate_number",
        "prompt": (
            "def truncate_number(number: float) -> float:\n"
            "    \"\"\" Return the fractional part of number. \"\"\"\n"
            "    # your code here\n"
            "    return 0.0\n"
        ),
        "test": (
            "assert abs(truncate_number(3.5) - 0.5) < 1e-9\n"
            "assert abs(truncate_number(1.25) - 0.25) < 1e-9\n"
            "assert abs(truncate_number(123.0) - 0.0) < 1e-9\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/2",
        "language": "python",
        "entry_point": "below_zero",
        "prompt": (
            "from typing import List\n\n"
            "def below_zero(operations: List[int]) -> bool:\n"
            "    \"\"\" Return True if the running sum ever goes below zero. \"\"\"\n"
            "    # your code here\n"
            "    return False\n"
        ),
        "test": (
            "assert below_zero([1, -2, 3, 4, -3, 2, 3]) == False\n"
            "assert below_zero([1, -4, 3, 4, -3, 2, 3]) == True\n"
            "assert below_zero([]) == False\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/3",
        "language": "python",
        "entry_point": "mean_absolute_deviation",
        "prompt": (
            "from typing import List\n\n"
            "def mean_absolute_deviation(numbers: List[float]) -> float:\n"
            "    \"\"\" Return the mean absolute deviation of numbers around their mean. \"\"\"\n"
            "    # your code here\n"
            "    return 0.0\n"
        ),
        "test": (
            "assert abs(mean_absolute_deviation([1.0, 2.0, 3.0, 4.0]) - 1.0) < 1e-6\n"
            "assert abs(mean_absolute_deviation([1.0, 2.0, 3.0]) - 2/3) < 1e-6\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/4",
        "language": "python",
        "entry_point": "intersperse",
        "prompt": (
            "from typing import List\n\n"
            "def intersperse(numbers: List[int], delimiter: int) -> List[int]:\n"
            "    \"\"\" Insert delimiter between each element of numbers. \"\"\"\n"
            "    # your code here\n"
            "    return []\n"
        ),
        "test": (
            "assert intersperse([1, 2, 3], 4) == [1, 4, 2, 4, 3]\n"
            "assert intersperse([1, 2], 0) == [1, 0, 2]\n"
            "assert intersperse([], 9) == []\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/5",
        "language": "python",
        "entry_point": "rolling_max",
        "prompt": (
            "from typing import List\n\n"
            "def rolling_max(numbers: List[int]) -> List[int]:\n"
            "    \"\"\" Return running maximum for each prefix of numbers. \"\"\"\n"
            "    # your code here\n"
            "    return []\n"
        ),
        "test": (
            "assert rolling_max([1, 2, 3, 2, 3, 4, 2]) == [1, 2, 3, 3, 3, 4, 4]\n"
            "assert rolling_max([3, 2, 1]) == [3, 3, 3]\n"
            "assert rolling_max([]) == []\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/6",
        "language": "python",
        "entry_point": "is_palindrome",
        "prompt": (
            "def is_palindrome(text: str) -> bool:\n"
            "    \"\"\" Return True if text is a palindrome. \"\"\"\n"
            "    # your code here\n"
            "    return False\n"
        ),
        "test": (
            "assert is_palindrome('racecar') == True\n"
            "assert is_palindrome('hello') == False\n"
            "assert is_palindrome('') == True\n"
            "assert is_palindrome('a') == True\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/7",
        "language": "python",
        "entry_point": "largest_divisor",
        "prompt": (
            "def largest_divisor(n: int) -> int:\n"
            "    \"\"\" Return the largest integer that divides n evenly and is smaller than n. \"\"\"\n"
            "    # your code here\n"
            "    return 1\n"
        ),
        "test": (
            "assert largest_divisor(15) == 5\n"
            "assert largest_divisor(27) == 9\n"
            "assert largest_divisor(100) == 50\n"
            "assert largest_divisor(13) == 1\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/8",
        "language": "python",
        "entry_point": "is_prime",
        "prompt": (
            "def is_prime(n: int) -> bool:\n"
            "    \"\"\" Return True if n is a prime number. \"\"\"\n"
            "    # your code here\n"
            "    return False\n"
        ),
        "test": (
            "assert is_prime(1) == False\n"
            "assert is_prime(2) == True\n"
            "assert is_prime(7) == True\n"
            "assert is_prime(9) == False\n"
            "assert is_prime(11) == True\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/9",
        "language": "python",
        "entry_point": "fib",
        "prompt": (
            "def fib(n: int) -> int:\n"
            "    \"\"\" Return the n-th Fibonacci number (0-indexed: fib(0)=0, fib(1)=1). \"\"\"\n"
            "    # your code here\n"
            "    return 0\n"
        ),
        "test": (
            "assert fib(0) == 0\n"
            "assert fib(1) == 1\n"
            "assert fib(7) == 13\n"
            "assert fib(10) == 55\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/10",
        "language": "python",
        "entry_point": "filter_by_substring",
        "prompt": (
            "from typing import List\n\n"
            "def filter_by_substring(strings: List[str], substring: str) -> List[str]:\n"
            "    \"\"\" Return strings that contain the given substring. \"\"\"\n"
            "    # your code here\n"
            "    return []\n"
        ),
        "test": (
            "assert filter_by_substring(['abc', 'bacd', 'cde', 'array'], 'a') == ['abc', 'bacd', 'array']\n"
            "assert filter_by_substring(['hello', 'world'], 'xyz') == []\n"
            "assert filter_by_substring([], 'x') == []\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/11",
        "language": "python",
        "entry_point": "how_many_times",
        "prompt": (
            "def how_many_times(string: str, substring: str) -> int:\n"
            "    \"\"\" Count overlapping occurrences of substring in string. \"\"\"\n"
            "    # your code here\n"
            "    return 0\n"
        ),
        "test": (
            "assert how_many_times('aaa', 'aa') == 2\n"
            "assert how_many_times('hello', 'l') == 2\n"
            "assert how_many_times('abc', 'xyz') == 0\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/12",
        "language": "python",
        "entry_point": "count_upper",
        "prompt": (
            "def count_upper(s: str) -> int:\n"
            "    \"\"\" Count uppercase letters in s. \"\"\"\n"
            "    # your code here\n"
            "    return 0\n"
        ),
        "test": (
            "assert count_upper('Hello World') == 2\n"
            "assert count_upper('hello') == 0\n"
            "assert count_upper('ABC') == 3\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/13",
        "language": "python",
        "entry_point": "sum_squares",
        "prompt": (
            "def sum_squares(n: int) -> int:\n"
            "    \"\"\" Return sum of squares of all integers from 1 to n inclusive. \"\"\"\n"
            "    # your code here\n"
            "    return 0\n"
        ),
        "test": (
            "assert sum_squares(1) == 1\n"
            "assert sum_squares(3) == 14\n"
            "assert sum_squares(5) == 55\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/14",
        "language": "python",
        "entry_point": "max_element",
        "prompt": (
            "from typing import List\n\n"
            "def max_element(lst: List[int]) -> int:\n"
            "    \"\"\" Return the maximum element in lst. \"\"\"\n"
            "    # your code here\n"
            "    return 0\n"
        ),
        "test": (
            "assert max_element([1, 2, 3]) == 3\n"
            "assert max_element([5, 3, 8, 1]) == 8\n"
            "assert max_element([-1, -5, -3]) == -1\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/15",
        "language": "python",
        "entry_point": "fizzbuzz",
        "prompt": (
            "def fizzbuzz(n: int) -> int:\n"
            "    \"\"\" Return count of integers in [1, n] divisible by 11 or 13. \"\"\"\n"
            "    # your code here\n"
            "    return 0\n"
        ),
        "test": (
            "assert fizzbuzz(50) == 6\n"
            "assert fizzbuzz(78) == 11\n"
            "assert fizzbuzz(79) == 11\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/16",
        "language": "python",
        "entry_point": "unique_elements",
        "prompt": (
            "from typing import List\n\n"
            "def unique_elements(lst: List[int]) -> List[int]:\n"
            "    \"\"\" Return unique elements from lst preserving first-occurrence order. \"\"\"\n"
            "    # your code here\n"
            "    return []\n"
        ),
        "test": (
            "assert unique_elements([1, 2, 3, 2, 1]) == [1, 2, 3]\n"
            "assert unique_elements([5, 5, 5]) == [5]\n"
            "assert unique_elements([]) == []\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/17",
        "language": "python",
        "entry_point": "median",
        "prompt": (
            "from typing import List\n\n"
            "def median(lst: List[float]) -> float:\n"
            "    \"\"\" Return the median of lst. \"\"\"\n"
            "    # your code here\n"
            "    return 0.0\n"
        ),
        "test": (
            "assert median([3, 1, 2]) == 2.0\n"
            "assert median([3, 1, 2, 4]) == 2.5\n"
            "assert median([5]) == 5.0\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/18",
        "language": "python",
        "entry_point": "count_vowels",
        "prompt": (
            "def count_vowels(s: str) -> int:\n"
            "    \"\"\" Count vowels (a, e, i, o, u) case-insensitively in s. \"\"\"\n"
            "    # your code here\n"
            "    return 0\n"
        ),
        "test": (
            "assert count_vowels('hello') == 2\n"
            "assert count_vowels('AEIOUaeiou') == 10\n"
            "assert count_vowels('rhythm') == 0\n"
            "print('PASS')\n"
        ),
    },
    {
        "task_id": "MultiPL-E/python/19",
        "language": "python",
        "entry_point": "pairs_sum_to_zero",
        "prompt": (
            "from typing import List\n\n"
            "def pairs_sum_to_zero(l: List[int]) -> bool:\n"
            "    \"\"\" Return True if any two distinct elements in l sum to zero. \"\"\"\n"
            "    # your code here\n"
            "    return False\n"
        ),
        "test": (
            "assert pairs_sum_to_zero([1, 3, 5, 0]) == False\n"
            "assert pairs_sum_to_zero([1, 3, -2, 1]) == False\n"
            "assert pairs_sum_to_zero([1, 2, 3, -4]) == False\n"
            "assert pairs_sum_to_zero([1, 2, 3, -2]) == True\n"
            "assert pairs_sum_to_zero([-1, 1]) == True\n"
            "print('PASS')\n"
        ),
    },
]

# Combined problems list for convenience
_ALL_PROBLEMS = (
    _JS_PROBLEMS + _GO_PROBLEMS + _TS_PROBLEMS + _C_PROBLEMS + _CPP_PROBLEMS + _JAVA_PROBLEMS
    + _RUBY_PROBLEMS + _PHP_PROBLEMS + _LUA_PROBLEMS + _R_PROBLEMS
    + _RUST_PROBLEMS + _JULIA_PROBLEMS + _CS_PROBLEMS + _BASH_PROBLEMS
    + _SWIFT_PROBLEMS + _SCALA_PROBLEMS + _PERL_PROBLEMS + _RACKET_PROBLEMS
    + _POWERSHELL_PROBLEMS + _PYTHON_PROBLEMS
)


# ── Code extractors ────────────────────────────────────────────────────────────


def _extract_code_for_lang(response: str, lang: str) -> str:
    """Extract language-specific code block from model response.

    Priority:
    1. ```<lang> ... ``` fenced block
    2. ``` ... ``` generic fenced block
    3. Full response fallback
    """
    # Strip <think>...</think> reasoning blocks
    response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
    if "<think>" in response:
        response = re.sub(r"<think>.*", "", response, flags=re.DOTALL).strip()

    # Map lang → fence identifiers to try
    lang_tags = {
        "js": ["javascript", "js"],
        "ts": ["typescript", "ts"],
        "go": ["go"],
        "c": ["c"],
        "cpp": ["cpp", "c\\+\\+", "cxx"],
        "rust": ["rust"],
        "java": ["java"],
    }
    tags = lang_tags.get(lang, [lang])

    for tag in tags:
        m = re.search(rf"```{tag}\s*\n(.*?)```", response, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Generic fenced block
    m = re.search(r"```\s*\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Fallback: raw response
    return response.strip()


# ── Sandbox executors ──────────────────────────────────────────────────────────


def _run_js(code: str, test_code: str) -> tuple[bool, str]:
    """Execute JS code + assertions with node."""
    full = code + "\n" + test_code
    try:
        result = subprocess.run(
            ["node", "-e", full],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin"},
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]


def _run_go(code: str) -> tuple[bool, str]:
    """Write Go code to temp file and run with `go run`."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".go", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
            f.write(code)
            tmp_path = f.name
        result = subprocess.run(
            ["go", "run", tmp_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/usr/local/go/bin:/bin", "HOME": "/tmp", "GOPATH": "/tmp/gopath"},  # nosec B108 -- benchmark sandbox tmp path
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        passed = result.returncode == 0 and "PASS" in result.stdout
        err = (result.stderr or result.stdout)[:500] if not passed else ""
        return passed, err
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _run_ts(code: str, test_code: str) -> tuple[bool, str]:
    """Execute TypeScript code + assertions with npx tsx."""
    full = code + "\n" + test_code
    try:
        result = subprocess.run(
            ["npx", "tsx", "-e", full],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/usr/local/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")},  # nosec B108 -- benchmark sandbox tmp path
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]


def _run_c(code: str) -> tuple[bool, str]:
    """Write C code to temp file, compile with gcc, and run."""
    src_path = None
    bin_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
            f.write(code)
            src_path = f.name
        bin_path = src_path.replace(".c", "")
        # Compile
        comp = subprocess.run(
            ["gcc", "-o", bin_path, src_path, "-lm"],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if comp.returncode != 0:
            return False, f"COMPILE ERROR: {(comp.stderr or comp.stdout)[:400]}"
        # Run
        result = subprocess.run(
            [bin_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        passed = result.returncode == 0 and "PASS" in result.stdout
        err = (result.stderr or result.stdout)[:500] if not passed else ""
        return passed, err
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        for p in (src_path, bin_path):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass


def _run_cpp(code: str) -> tuple[bool, str]:
    """Write C++ code to temp file, compile with g++ -std=c++17, and run."""
    src_path = None
    bin_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
            f.write(code)
            src_path = f.name
        bin_path = src_path.replace(".cpp", "")
        # Compile
        comp = subprocess.run(
            ["g++", "-std=c++17", "-o", bin_path, src_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if comp.returncode != 0:
            return False, f"COMPILE ERROR: {(comp.stderr or comp.stdout)[:400]}"
        # Run
        result = subprocess.run(
            [bin_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        passed = result.returncode == 0 and "PASS" in result.stdout
        err = (result.stderr or result.stdout)[:500] if not passed else ""
        return passed, err
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        for p in (src_path, bin_path):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass


def _run_java(code: str) -> tuple[bool, str]:
    """Write Java code to temp dir, compile with javac, and run.

    Java requires the class name to match the filename.  We extract the
    public class name from the source (defaulting to 'Solution') and use
    that as the filename.
    """
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(dir="/tmp", prefix="java_")  # nosec B108 -- benchmark sandbox tmp path
        # Extract public class name
        m = re.search(r"public\s+class\s+(\w+)", code)
        class_name = m.group(1) if m else "Solution"
        src_path = os.path.join(tmp_dir, f"{class_name}.java")
        with open(src_path, "w") as f:
            f.write(code)
        # Compile
        comp = subprocess.run(
            ["javac", src_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd=tmp_dir,
        )
        if comp.returncode != 0:
            return False, f"COMPILE ERROR: {(comp.stderr or comp.stdout)[:400]}"
        # Run
        result = subprocess.run(
            ["java", "-cp", tmp_dir, class_name],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd=tmp_dir,
        )
        passed = result.returncode == 0 and "PASS" in result.stdout
        err = (result.stderr or result.stdout)[:500] if not passed else ""
        return passed, err
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        if tmp_dir:
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass


def _run_ruby(code: str, test_code: str) -> tuple[bool, str]:
    """Execute Ruby code + test assertions with /usr/bin/ruby."""
    full = code + "\n" + test_code
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rb", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
            f.write(full)
            tmp_path = f.name
        result = subprocess.run(
            ["/usr/bin/ruby", tmp_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _run_php(code: str, test_code: str) -> tuple[bool, str]:
    """Execute PHP code + test assertions with /usr/bin/php."""
    # PHP files must start with <?php; ensure it's present and test is appended
    if "<?php" in code:
        full = code.rstrip() + "\n" + test_code
    else:
        full = "<?php\n" + code + "\n" + test_code
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".php", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
            f.write(full)
            tmp_path = f.name
        result = subprocess.run(
            ["/usr/bin/php", tmp_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _run_lua(code: str, test_code: str) -> tuple[bool, str]:
    """Execute Lua code + test assertions with /usr/bin/lua."""
    full = code + "\n" + test_code
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lua", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
            f.write(full)
            tmp_path = f.name
        result = subprocess.run(
            ["/usr/bin/lua", tmp_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _run_r(code: str, test_code: str) -> tuple[bool, str]:
    """Execute R code + test assertions with /usr/bin/Rscript."""
    full = code + "\n" + test_code
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".R", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
            f.write(full)
            tmp_path = f.name
        result = subprocess.run(
            ["/usr/bin/Rscript", tmp_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _run_rust(code: str) -> tuple[bool, str]:
    """Write Rust code to temp file, compile with rustc, and run."""
    src_path = None
    bin_path = None
    rustc = os.path.expanduser("~/.cargo/bin/rustc")
    if not os.path.exists(rustc):
        rustc = "rustc"  # fallback to PATH
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rs", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
            f.write(code)
            src_path = f.name
        bin_path = src_path.replace(".rs", "")
        # Compile (rustc can be slow — allow 3× timeout)
        comp = subprocess.run(
            [rustc, "-o", bin_path, src_path],
            timeout=EXEC_TIMEOUT * 3,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if comp.returncode != 0:
            return False, f"COMPILE ERROR: {(comp.stderr or comp.stdout)[:400]}"
        # Run
        result = subprocess.run(
            [bin_path],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        passed = result.returncode == 0 and "PASS" in result.stdout
        err = (result.stderr or result.stdout)[:500] if not passed else ""
        return passed, err
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        for p in (src_path, bin_path):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass


def _run_julia(code: str, test_code: str) -> tuple[bool, str]:
    """Execute Julia code + test assertions with julia."""
    full = code + "\n" + test_code
    julia = os.path.expanduser("~/.juliaup/bin/julia")
    if not os.path.exists(julia):
        julia = "/home/peter/.julia/juliaup/julia-1.12.6+0.x64.linux.gnu/bin/julia"  # fallback to PATH
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jl", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
            f.write(full)
            tmp_path = f.name
        result = subprocess.run(
            [julia, tmp_path],
            timeout=EXEC_TIMEOUT * 3,  # Julia JIT startup
            capture_output=True,
            text=True,
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _run_cs(code: str) -> tuple[bool, str]:
    """Write C# code to temp project dir and run with dotnet."""
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(dir="/tmp", prefix="cs_")  # nosec B108 -- benchmark sandbox tmp path
        src_path = os.path.join(tmp_dir, "Program.cs")
        proj_path = os.path.join(tmp_dir, "Program.csproj")
        with open(src_path, "w") as f:
            f.write(code)
        with open(proj_path, "w") as f:
            f.write(
                "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
                "  <PropertyGroup>\n"
                "    <OutputType>Exe</OutputType>\n"
                "    <TargetFramework>net8.0</TargetFramework>\n"
                "    <Nullable>enable</Nullable>\n"
                "  </PropertyGroup>\n"
                "</Project>\n"
            )
        result = subprocess.run(
            ["dotnet", "run", "--project", proj_path],
            timeout=EXEC_TIMEOUT * 6,  # dotnet first-run is slow
            capture_output=True,
            text=True,
            cwd=tmp_dir,
            env={**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"},
        )
        passed = result.returncode == 0 and "PASS" in result.stdout
        err = (result.stderr or result.stdout)[:500] if not passed else ""
        return passed, err
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]
    finally:
        if tmp_dir:
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass


def _run_bash(code: str, test_code: str) -> tuple[bool, str]:
    """Execute Bash function + test assertions in a temporary script."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False) as f:
        f.write("#!/usr/bin/env bash\nset -euo pipefail\n")
        f.write(code + "\n")
        f.write(test_code + "\n")
        fname = f.name
    try:
        r = subprocess.run(["bash", fname], capture_output=True, text=True, timeout=10)
        return r.returncode == 0, (r.stdout + r.stderr)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


def _run_swift(code: str, test_code: str) -> tuple[bool, str]:
    """Compile Swift code + test assertions with swiftc and run."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".swift", mode="w", delete=False) as f:
        f.write(code + "\n" + test_code + "\n")
        fname = f.name
    exe = fname.replace(".swift", "")
    try:
        cr = subprocess.run(["swiftc", "-o", exe, fname], capture_output=True, text=True, timeout=30)
        if cr.returncode != 0:
            return False, cr.stderr[:400]
        r = subprocess.run([exe], capture_output=True, text=True, timeout=10)
        return r.returncode == 0, (r.stdout + r.stderr)[:400]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)
    finally:
        for p in [fname, exe]:
            try:
                os.unlink(p)
            except Exception:
                pass


def _run_scala(code: str, test_code: str) -> tuple[bool, str]:
    """Compile Scala code + test assertions with scalac and run."""
    import os
    # Scala problems expect the model to keep `object Main extends App {` open;
    # the test code contains the closing `}`. Strip any trailing `}` the model added.
    stripped = code.rstrip()
    if stripped.endswith("}"):
        # Remove the last closing brace so test assertions land inside the object
        last_brace = stripped.rfind("}")
        stripped = stripped[:last_brace].rstrip()
    combined = stripped + "\n" + test_code + "\n"
    with tempfile.NamedTemporaryFile(suffix=".scala", mode="w", delete=False, dir="/tmp") as f:  # nosec B108 -- benchmark sandbox tmp path
        f.write(combined)
        fname = f.name
    try:
        coursier_bin = os.path.expanduser("~/.local/share/coursier/bin")
        scalac = shutil.which("scalac") or os.path.join(coursier_bin, "scalac")
        cr = subprocess.run([scalac, "-d", "/tmp", fname], capture_output=True, text=True, timeout=60)  # nosec B108 -- benchmark sandbox tmp path
        if cr.returncode != 0:
            return False, cr.stderr[:400]
        # Scala 3 via coursier needs runtime jars on classpath
        import glob as _glob
        cache = os.path.expanduser("~/.cache/coursier/v1")
        scala3_libs = _glob.glob(f"{cache}/**/scala3-library_3-*.jar", recursive=True)
        scala2_libs = _glob.glob(f"{cache}/**/scala-library-*.jar", recursive=True)
        # Pick highest version (sort descending)
        scala3_jar = sorted(scala3_libs)[-1] if scala3_libs else ""
        scala2_jar = sorted(scala2_libs)[-1] if scala2_libs else ""
        cp = ":".join(filter(None, ["/tmp", scala3_jar, scala2_jar]))  # nosec B108 -- benchmark sandbox tmp path
        r = subprocess.run(
            ["java", "-classpath", cp, "Main"],
            capture_output=True, text=True, timeout=20,
        )
        passed = r.returncode == 0 and "PASS" in r.stdout
        return passed, (r.stdout + r.stderr)[:400]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


def _run_perl(code: str, test_code: str) -> tuple[bool, str]:
    """Execute Perl code + test assertions with perl."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".pl", mode="w", delete=False) as f:
        f.write(code + "\n" + test_code + "\n")
        fname = f.name
    try:
        r = subprocess.run(["perl", "-w", fname], capture_output=True, text=True, timeout=10)
        return r.returncode == 0, (r.stdout + r.stderr)[:400]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


def _run_racket(code: str, test_code: str) -> tuple[bool, str]:
    """Execute Racket code + test assertions with racket."""
    import os
    with tempfile.NamedTemporaryFile(suffix=".rkt", mode="w", delete=False) as f:
        if not code.startswith("#lang"):
            f.write("#lang racket\n")
        f.write(code + "\n" + test_code + "\n")
        fname = f.name
    try:
        r = subprocess.run(["racket", fname], capture_output=True, text=True, timeout=15)
        return r.returncode == 0, (r.stdout + r.stderr)[:400]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


def _run_powershell(code: str, test_code: str) -> tuple[bool, str]:
    """Execute PowerShell code + test assertions with pwsh."""
    import os
    import shutil
    pwsh = shutil.which("pwsh") or "pwsh"
    with tempfile.NamedTemporaryFile(suffix=".ps1", mode="w", delete=False) as f:
        f.write(code + "\n" + test_code + "\n")
        fname = f.name
    try:
        r = subprocess.run(
            [pwsh, "-NonInteractive", "-NoProfile", "-File", fname],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0, (r.stdout + r.stderr)[:400]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


def _run_python(code: str, test_code: str) -> tuple[bool, str]:
    """Execute Python code + test assertions with python3."""
    import os
    import sys
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code + "\n" + test_code + "\n")
        fname = f.name
    try:
        r = subprocess.run(
            [sys.executable, fname],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0, (r.stdout + r.stderr)[:400]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


def run_language(code: str, lang: str, timeout: int = EXEC_TIMEOUT) -> bool:
    """Execute generated code in sandbox. Returns True if tests pass."""
    if lang == "js":
        passed, _ = _run_js(code, "")
        return passed
    if lang == "ts":
        passed, _ = _run_ts(code, "")
        return passed
    if lang == "go":
        passed, _ = _run_go(code)
        return passed
    if lang == "c":
        passed, _ = _run_c(code)
        return passed
    if lang == "cpp":
        passed, _ = _run_cpp(code)
        return passed
    if lang == "java":
        passed, _ = _run_java(code)
        return passed
    if lang == "ruby":
        passed, _ = _run_ruby(code, "")
        return passed
    if lang == "php":
        passed, _ = _run_php(code, "")
        return passed
    if lang == "lua":
        passed, _ = _run_lua(code, "")
        return passed
    if lang == "r":
        passed, _ = _run_r(code, "")
        return passed
    if lang == "rust":
        passed, _ = _run_rust(code)
        return passed
    if lang == "julia":
        passed, _ = _run_julia(code, "")
        return passed
    if lang == "cs":
        passed, _ = _run_cs(code)
        return passed
    return False


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=False, timeout=300.0)  # nosec B501 -- benchmark local server, SSL not applicable


async def _query(
    client: httpx.AsyncClient, mullm_url: str, content: str, force_tier: str = "", provider: str = "", model: str = "", think: bool = False,
    direct_openai_url: str = "", direct_openai_model: str = "",
) -> dict[str, Any]:
    """POST /query and return the JSON response dict."""
    if direct_openai_url and direct_openai_model:
        try:
            r = await client.post(
                f"{direct_openai_url}/v1/completions",
                json={"model": direct_openai_model, "prompt": content, "max_tokens": 800, "temperature": 0, "stream": False},
                timeout=120,
            )
            r.raise_for_status()
            d = r.json()
            return {"response": d["choices"][0]["text"], "tier_used": "local", "model_used": direct_openai_model, "cost": 0}
        except Exception as exc:
            return {"error": str(exc)[:300], "response": "", "tier_used": "error", "model_used": "error", "cost": 0}
    payload: dict[str, Any] = {
        "content": content,
        "stream": False,
        "skip_cache": True,
        "source": "api",
        "temperature": 0.0,
        "min_complexity": 3,
        "context": {"bench_mode": True, "think": think, "num_predict": 2048},
    }
    if force_tier:
        payload["force_tier"] = force_tier
    if provider:
        payload["provider"] = provider
    if model:
        payload["model"] = model
    try:
        r = await client.post(f"{mullm_url}/query", json=payload)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"error": str(exc)[:300], "response": "", "tier_used": "error", "model_used": "error", "cost": 0}


# ── Runner ────────────────────────────────────────────────────────────────────


async def run_multipl_e(
    mullm_url: str = MULLM_DEFAULT,
    force_tier: str = "",
    limit: int = 20,
    languages: list[str] | None = None,
    progress_cb=None,
    round_robin_models: list[tuple[str, str]] | None = None,
    vllm_base_url: str = "",
    vllm_model: str = "",
    max_consecutive_failures: int = 5,
) -> dict:
    """Run MultiPL-E benchmark through muLLM (or directly against vLLM).

    Parameters
    ----------
    mullm_url:                  muLLM server URL
    force_tier:                 force a specific tier ('local', 'cloud', etc.)
    limit:                      max problems PER language (default 20)
    languages:                  list of language codes to test; None = all available
    progress_cb:                optional callable(lang, idx, passed_count)
    round_robin_models:         list of (provider, model) tuples to cycle through per-problem
    vllm_base_url:              if set, call vLLM /v1/completions directly (bypasses muLLM)
    vllm_model:                 model name to pass to vLLM (required when vllm_base_url is set)
    max_consecutive_failures:   abort entire run if this many consecutive failures across all langs
    """
    available = {
        "js": _JS_PROBLEMS,
        "ts": _TS_PROBLEMS,
        "go": _GO_PROBLEMS,
        "c": _C_PROBLEMS,
        "cpp": _CPP_PROBLEMS,
        "java": _JAVA_PROBLEMS,
        "ruby": _RUBY_PROBLEMS,
        "php": _PHP_PROBLEMS,
        "lua": _LUA_PROBLEMS,
        "r": _R_PROBLEMS,
        "rust": _RUST_PROBLEMS,
        "julia": _JULIA_PROBLEMS,
        "cs": _CS_PROBLEMS,
        "bash": _BASH_PROBLEMS,
        "swift": _SWIFT_PROBLEMS,
        "scala": _SCALA_PROBLEMS,
        "perl": _PERL_PROBLEMS,
        "racket": _RACKET_PROBLEMS,
        "powershell": _POWERSHELL_PROBLEMS,
        "python": _PYTHON_PROBLEMS,
    }
    if languages is None:
        languages = list(available.keys())

    # Skip languages whose runtime is not installed
    _runtime_check = {
        "racket": "racket",
        "swift": "swift",
        "scala": "scalac",
        "rust": "rustc",
        "powershell": "pwsh",
    }
    skipped_langs = []
    for lang in list(languages):
        bin_name = _runtime_check.get(lang)
        if bin_name:
            import shutil as _shutil
            # also check coursier path for scala
            coursier_bin = os.path.join(os.path.expanduser("~"), ".local", "share", "coursier", "bin")
            found = _shutil.which(bin_name) or (
                lang == "scala" and os.path.exists(os.path.join(coursier_bin, bin_name))
            )
            if not found:
                skipped_langs.append(lang)
                languages = [l for l in languages if l != lang]
    if skipped_langs:
        print(f"  [skip] runtime not found for: {', '.join(skipped_langs)}", flush=True)

    # Build problem list capped at limit per language
    problems_by_lang: dict[str, list[dict]] = {}
    for lang in languages:
        if lang in available:
            problems_by_lang[lang] = available[lang][:limit]

    all_results: list[dict] = []
    per_language: dict[str, dict] = {}
    total_passed = 0
    total_count = 0
    consecutive_failures = 0
    aborted = False

    async with _make_client() as client:
        for lang, problems in problems_by_lang.items():
            if aborted:
                break
            lang_passed = 0

            for idx, prob in enumerate(problems):
                if aborted:
                    break
                t0 = time.perf_counter()

                lang_name = {
                    "js": "JavaScript",
                    "ts": "TypeScript",
                    "go": "Go",
                    "c": "C",
                    "cpp": "C++",
                    "java": "Java",
                    "ruby": "Ruby",
                    "php": "PHP",
                    "lua": "Lua",
                    "r": "R",
                    "rust": "Rust",
                    "julia": "Julia",
                    "cs": "C#",
                    "bash": "Bash",
                    "swift": "Swift",
                    "scala": "Scala",
                    "perl": "Perl",
                    "racket": "Racket",
                }.get(lang, lang)
                lang_hint = ""
                if lang == "js":
                    lang_hint = (
                        " Write standard ES6+ JavaScript."
                        " Define only the single function named in the scaffold — no extra helpers unless called by it."
                        " Do not use TypeScript syntax (no type annotations, no interfaces)."
                        " Return only the complete runnable JavaScript code; no prose outside code fences."
                    )
                elif lang == "bash":
                    lang_hint = (
                        " Use only POSIX bash/awk idioms."
                        " Do not name awk variables or functions after builtins"
                        " (split, sub, gsub, substr, match, index, length, print, sin, cos, log, exp, sqrt)."
                        " For float arithmetic use bc -l; wrap result in printf to ensure leading zero"
                        " (e.g. printf '%.10f\\n' $(echo 'scale=10; ...' | bc -l))."
                        " No awk abs() — use (x<0?-x:x) instead."
                        " Avoid bashisms that require bash 4.4+."
                    )
                elif lang == "go":
                    lang_hint = (
                        " Do not use stdlib package names (strings, fmt, math, sort, strconv) as"
                        " variable names — they shadow the import."
                        " Preserve ALL import statements from the scaffold; do not remove any."
                        " Always call package-level functions with their qualifier:"
                        " strings.Join(slice, sep), not slice.Join(sep)."
                    )
                elif lang == "c":
                    lang_hint = (
                        " Preserve const qualifiers on all function parameters exactly as given in the scaffold."
                        " Use standard C99/C11 string functions (strcmp, strlen, strcpy, sprintf)."
                    )
                elif lang == "php":
                    lang_hint = (
                        " Use single or double quotes for strings — PHP does not support backtick"
                        " template literals. Use double-quoted strings for variable interpolation: \"$var\"."
                    )
                elif lang == "julia":
                    lang_hint = (
                        " Import Statistics with 'using Statistics' if you need mean/std/var."
                        " Use isletter(c) || isdigit(c) instead of isalnum(c) — Julia has no isalnum."
                        " Use isuppercase/islowercase not isupper/islower."
                    )
                prompt = (
                    f"Complete this {lang_name} function.{lang_hint} "
                    f"Return ONLY the complete runnable {lang_name} code — "
                    f"no explanation, no markdown preamble outside code fences."
                    f" Use well-known algorithms and standard library functions."
                    f" Verify edge cases: empty input, single elements, zero, negative numbers,"
                    f" and prime numbers where relevant.\n\n"
                    f"{prob['prompt']}"
                )

                rr_provider, rr_model = "", ""
                if round_robin_models:
                    rr_provider, rr_model = round_robin_models[total_count % len(round_robin_models)]
                _timeout = 300.0
                try:
                    data = await asyncio.wait_for(
                        _query(client, mullm_url, prompt, force_tier, rr_provider, rr_model, think=False,
                               direct_openai_url=vllm_base_url, direct_openai_model=vllm_model),
                        timeout=_timeout,
                    )
                except TimeoutError:
                    data = {"error": "timeout after 300s", "response": "", "tier_used": "error", "model_used": "error", "cost": 0}
                latency_ms = (time.perf_counter() - t0) * 1000

                raw_response = data.get("response", "")
                code = _extract_code_for_lang(raw_response, lang)

                # Execute in sandbox
                if lang == "js":
                    # For JS problems the test assertions are separate from the function stub
                    passed, error = await asyncio.to_thread(_run_js, code, prob.get("test", ""))
                elif lang == "ts":
                    # TypeScript: same as JS — test assertions appended to generated code
                    passed, error = await asyncio.to_thread(_run_ts, code, prob.get("test", ""))
                elif lang == "go":
                    # For Go problems main() contains assertions; code must be a full file
                    # If model returned only the function body, wrap it with the original scaffold
                    if not re.search(r"^\s*func\s+main\s*\(", code, re.MULTILINE):
                        # Model returned only the function — merge back into the prompt scaffold
                        # Replace the stub body with the model's code
                        ep = prob["entry_point"]
                        scaffold = prob["prompt"]
                        # Find and replace the stub function body in the scaffold
                        stub_pattern = rf"(func\s+{re.escape(ep)}\s*\([^)]*\)[^{{]*\{{)[^}}]*\}}"
                        # Extract just the function (no main)
                        fn_match = re.search(rf"func\s+{re.escape(ep)}\s*\([^)]*\)[^\{{]*\{{.*?\n\}}", code, re.DOTALL)
                        if fn_match:
                            full_fn = fn_match.group(0)
                            # Splice into scaffold: replace stub with real function
                            code = re.sub(stub_pattern, full_fn, scaffold, flags=re.DOTALL)
                        else:
                            # Can't parse — use scaffold with model code injected before main
                            # Find where main() starts and insert model code before it
                            main_pos = scaffold.rfind("func main()")
                            if main_pos > 0:
                                code = scaffold[:main_pos] + code + "\n\n" + scaffold[main_pos:]
                            else:
                                code = scaffold  # fallback: run scaffold (will fail the stub)
                    passed, error = await asyncio.to_thread(_run_go, code)
                elif lang == "c":
                    # C: self-contained program with main() and assert()
                    # If model returned only the function, merge into scaffold
                    if "int main" not in code:
                        scaffold = prob["prompt"]
                        ep = prob["entry_point"]
                        # Try to find the function in model output and splice into scaffold
                        fn_match = re.search(
                            rf"(?:int|void|double|const\s+char\s*\*)\s+{re.escape(ep)}\s*\([^)]*\)\s*\{{.*?\n\}}",
                            code,
                            re.DOTALL,
                        )
                        if fn_match:
                            stub_pattern = (
                                rf"(?:int|void|double|const\s+char\s*\*)\s+{re.escape(ep)}\s*\([^)]*\)\s*\{{[^}}]*\}}"
                            )
                            code = re.sub(stub_pattern, fn_match.group(0), scaffold, count=1, flags=re.DOTALL)
                        else:
                            code = scaffold  # fallback
                    passed, error = await asyncio.to_thread(_run_c, code)
                elif lang == "cpp":
                    # C++: self-contained program with main() and assert()
                    if "int main" not in code:
                        scaffold = prob["prompt"]
                        ep = prob["entry_point"]
                        fn_match = re.search(
                            rf"(?:bool|int|double|string|vector|pair)\s*(?:<[^>]*>)?\s+{re.escape(ep)}\s*\([^)]*\)\s*\{{.*?\n\}}",
                            code,
                            re.DOTALL,
                        )
                        if fn_match:
                            stub_pattern = rf"(?:bool|int|double|string|vector|pair)\s*(?:<[^>]*>)?\s+{re.escape(ep)}\s*\([^)]*\)\s*\{{[^}}]*\}}"
                            code = re.sub(stub_pattern, fn_match.group(0), scaffold, count=1, flags=re.DOTALL)
                        else:
                            code = scaffold
                    passed, error = await asyncio.to_thread(_run_cpp, code)
                elif lang == "java":
                    # Java: self-contained program with public class Solution, main() has assertions
                    # If model returned only the method, merge into scaffold
                    if "public static void main" not in code:
                        scaffold = prob["prompt"]
                        ep = prob["entry_point"]
                        # Try to find the method in model output and splice into scaffold
                        fn_match = re.search(
                            rf"public\s+static\s+\S+\s+{re.escape(ep)}\s*\([^)]*\)\s*\{{.*?\n    \}}", code, re.DOTALL
                        )
                        if fn_match:
                            stub_pattern = rf"public\s+static\s+\S+\s+{re.escape(ep)}\s*\([^)]*\)\s*\{{[^}}]*\}}"
                            code = re.sub(stub_pattern, fn_match.group(0), scaffold, count=1, flags=re.DOTALL)
                        else:
                            code = scaffold  # fallback
                    passed, error = await asyncio.to_thread(_run_java, code)
                elif lang == "ruby":
                    passed, error = await asyncio.to_thread(_run_ruby, code, prob.get("test", ""))
                elif lang == "php":
                    passed, error = await asyncio.to_thread(_run_php, code, prob.get("test", ""))
                elif lang == "lua":
                    passed, error = await asyncio.to_thread(_run_lua, code, prob.get("test", ""))
                elif lang == "r":
                    passed, error = await asyncio.to_thread(_run_r, code, prob.get("test", ""))
                elif lang == "rust":
                    # Rust: self-contained program with main() and PASS output
                    passed, error = await asyncio.to_thread(_run_rust, code)
                elif lang == "julia":
                    passed, error = await asyncio.to_thread(_run_julia, code, prob.get("test", ""))
                elif lang == "cs":
                    # C#: self-contained program with Main() and PASS output
                    passed, error = await asyncio.to_thread(_run_cs, code)
                elif lang == "bash":
                    passed, error = await asyncio.to_thread(_run_bash, code, prob.get("test", ""))
                elif lang == "swift":
                    passed, error = await asyncio.to_thread(_run_swift, code, prob.get("test", ""))
                elif lang == "scala":
                    passed, error = await asyncio.to_thread(_run_scala, code, prob.get("test", ""))
                elif lang == "perl":
                    passed, error = await asyncio.to_thread(_run_perl, code, prob.get("test", ""))
                elif lang == "racket":
                    passed, error = await asyncio.to_thread(_run_racket, code, prob.get("test", ""))
                elif lang == "powershell":
                    passed, error = await asyncio.to_thread(_run_powershell, code, prob.get("test", ""))
                elif lang == "python":
                    passed, error = await asyncio.to_thread(_run_python, code, prob.get("test", ""))
                else:
                    passed, error = False, f"unsupported language: {lang}"

                if passed:
                    lang_passed += 1
                    total_passed += 1
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if max_consecutive_failures > 0 and consecutive_failures >= max_consecutive_failures:
                        print(f"  [ABORT] {consecutive_failures} consecutive failures — cancelling run", flush=True)
                        aborted = True
                total_count += 1

                all_results.append(
                    {
                        "task_id": prob["task_id"],
                        "language": lang,
                        "passed": passed,
                        "error": error,
                        "tier": data.get("tier_used", "unknown"),
                        "model": data.get("model_used", "unknown"),
                        "cost": data.get("cost", 0),
                        "latency_ms": round(latency_ms, 1),
                        "response_len": len(raw_response),
                        "response_text": code[:500],  # truncate for storage
                    }
                )

                status = "✓" if passed else "✗"
                print(f"  {lang} [{idx+1:2d}/{len(problems)}] {status} {latency_ms/1000:.1f}s{' err:'+error[:60] if error and not passed else ''}", flush=True)

                if progress_cb:
                    progress_cb(lang, idx + 1, lang_passed)

            lang_total = len(problems)
            per_language[lang] = {
                "pass_at_1": round(lang_passed / lang_total, 4) if lang_total else 0.0,
                "passed": lang_passed,
                "total": lang_total,
            }

    pass_at_1 = total_passed / total_count if total_count else 0.0
    return {
        "benchmark": "multipl_e",
        "pass_at_1": round(pass_at_1, 4),
        "passed": total_passed,
        "total": total_count,
        "per_language": per_language,
        "problems": all_results,
        "aborted": aborted,
    }
