# Malloy issues found while building MalloyBench

Every example is a complete query on the raw TPC-H tables, with no model file (item 15 needs a
one-line model, because a restricted query cannot call `duckdb.table()`), re-run on
`@malloydata/malloy` 0.0.435 (the latest release, 2 October 2026) with `@malloydata/db-duckdb`
0.0.435 (DuckDB 1.5.5). The right answers come from plain SQL on the same database. To reproduce,
in DuckDB run `INSTALL tpch; LOAD tpch; CALL dbgen(sf = 1);` and use a DuckDB connection named
`duckdb`; the data is generated deterministically, so the numbers match exactly.

Each issue was checked three ways: against the documentation at docs.malloydata.dev (quoted and
linked below), against the compiler's source (the 0.0.435 package, and Malloy's main branch as of
14 October 2026), and against Malloy's GitHub issues.

| # | What happens | Verdict | Upstream |
|---|---|---|---|
| 1 | `!~` with a filter expression matches instead of excluding | Bug in documented syntax | Reported as [#3159](https://github.com/malloydata/malloy/issues/3159) |
| 2 | `?` with a regular expression compares text | Bug in documented syntax | Reported as [#3160](https://github.com/malloydata/malloy/issues/3160) |
| 3 | `count()` through one `join_many` counts parents with no match | Bug in documented behavior | Open since 2024 (#1762) |
| 4 | A `limit:` refinement drops the view's `order_by:` | Bug in documented behavior | Fixed on main, not released (#3136) |
| 5 | `having:` on a dimension empties `all()` | Undocumented syntax Malloy accepts; should be an error | Reported as [#3163](https://github.com/malloydata/malloy/issues/3163) |
| 6 | `exclude()` of an outer dimension in a nest returns one group's count | Bug in documented behavior | Reported as [#3161](https://github.com/malloydata/malloy/issues/3161) |
| 7 | A join condition through the joined source's own join, or through a dimension defined by a join, breaks the SQL | Undocumented syntax Malloy accepts; should be an error | Open (#2486, #1482); dimension case added to [#2486](https://github.com/malloydata/malloy/issues/2486#issuecomment-6419519243) |
| 8 | A `nullif()` dimension averaged across a fan-out fails | DuckDB bug, not Malloy's | New (DuckDB) |
| 9 | `~` with a time or number range crashes the compiler | Bug in documented syntax | Reported as [#3162](https://github.com/malloydata/malloy/issues/3162) |
| 10 | Subtracting two dates gives an error about a logger | Error-reporting bug | Reported in [#3164](https://github.com/malloydata/malloy/issues/3164) |
| 11 | A `concat()` primary key counts the unmatched row | Modeling trap, not a bug | |
| 12 | `where:` needs commas between conditions | Design choice | Open request (#465) |
| 13 | `count(distinct x)` is an error | Design choice (Malloy 4.0) | Decided in PR #1422 |
| 14 | `d.year = 1995` compares a date to a number | Design choice | |
| 15 | In a restricted query, an unknown function suggests the `!` call restricted mode rejects | Error-reporting bug | Reported in [#3164](https://github.com/malloydata/malloy/issues/3164) |
| 16 | `project:` reports a missing colon | Error-reporting bug | Reported in [#3164](https://github.com/malloydata/malloy/issues/3164) |
| 17 | An aggregate cannot use another aggregate of the same query, and the errors point away | Missing feature; error-reporting bug | Open (#2276, #1947); messages reported in [#3164](https://github.com/malloydata/malloy/issues/3164) |
| 18 | A `#` note at the end of a query block reports an "unimplemented" statement | Error-reporting bug | Not reported (minor) |
| 19 | `&` or `\|` between two conditions reports "Alternation tree has no value" | Error-reporting bug | Open (#1083) |

So nine are Malloy bugs: six in behavior the docs describe (1, 2, 3, 4, 6 and 9), two in syntax
Malloy accepts without documenting it (5 and 7), and one in error reporting (10). Six of the nine
were new, and we reported all six on 20 October 2026, 10 as part of [#3164](https://github.com/malloydata/malloy/issues/3164). 3 and 7
were already open upstream (we added the trigger condition and the code location to #1762), and 4
is fixed on main. Issue 8 belongs to DuckDB, 11 is a trap
in how a model is written, and 12 to 14 are rules that models break often. Items 15 to 19 are
error messages that sent models in circles in the agentic runs. We reported 10, 15, 16 and the
messages of 17 together as [#3164](https://github.com/malloydata/malloy/issues/3164) (draft in [upstream/07-error-messages.md](upstream/07-error-messages.md)); 18 is minor and
19 is open upstream, so neither is in it. A list of small fixes to the docs is at the end.

## Wrong numbers, no error

The query compiles and runs, and the number is wrong.

**1. `!~` with a filter expression matches instead of excluding**

`l_shipmode !~ f'AIR'` compiles to `= 'AIR'`, so the query returns exactly the rows it was meant to
leave out.

```malloy
run: duckdb.table('lineitem') -> {
  where: l_shipmode !~ f'AIR'
  aggregate: lines is count()
}
```

- Malloy returns: 858,104 lines, the AIR lines
- Right answer: 5,143,111 lines

Generated SQL:

```sql
WHERE base."l_shipmode" = 'AIR'
```

- Docs: [Filter Expressions](https://docs.malloydata.dev/documentation/language/filter-expressions):
  "A filter expression is applied to a value with the `~` or `!~` operators."
- Code: the translator marks the match as negated (`filterMatch.notMatch = true`), and the SQL
  generator, `generateAppliedFilter` in `model/expression_compiler`, never reads that flag. The same
  on main.
- Upstream: reported as [malloydata/malloy#3159](https://github.com/malloydata/malloy/issues/3159).

Works instead: `l_shipmode != 'AIR'` returns 5,143,111:

```malloy
run: duckdb.table('lineitem') -> {
  where: l_shipmode != 'AIR'
  aggregate: lines is count()
}
```

**2. `?` with a regular expression compares text**

`l_shipmode ? r'^A'` checks whether the ship mode equals the text `^A`. The docs say it matches the
pattern, as `~` does.

```malloy
run: duckdb.table('lineitem') -> {
  where: l_shipmode ? r'^A'
  aggregate: lines is count()
}
```

- Malloy returns: 0 lines
- Right answer: 858,104 lines (AIR is the one mode starting with A)

Generated SQL:

```sql
WHERE base."l_shipmode"='^A'
```

- Docs: [Expressions](https://docs.malloydata.dev/documentation/language/expressions), under
  Application: `name ? r'Z$'` means `name ~ r'Z$'`. The [Apply](https://docs.malloydata.dev/documentation/language/apply)
  page says the same.
- Code: `?` is an equality (`=`) comparison, and a regular expression becomes a pattern match only
  under `~` and `!~`. So `l_shipmode = r'^A'` also compares text, and the alternation
  `l_shipmode ? r'^A' | r'^T'` becomes `IN ('^A','^T')`. The same on main.
- Upstream: reported as [malloydata/malloy#3160](https://github.com/malloydata/malloy/issues/3160).

Works instead: `l_shipmode ~ r'^A'` returns 858,104:

```malloy
run: duckdb.table('lineitem') -> {
  where: l_shipmode ~ r'^A'
  aggregate: lines is count()
}
```

**3. `count()` through one `join_many` counts parents with no match**

When the joined source declares a `primary_key` and is the query's only `join_many`, `orders.count()`
becomes `COUNT(1)` over the left join, so each of the 50,004 customers without an order adds one.
Without the primary key, Malloy makes its own key and counts right; with a second `join_many` in the
query, the same measure becomes a distinct count and comes out right too.

```malloy
source: orders is duckdb.table('orders') extend { primary_key: o_orderkey }
source: customers is duckdb.table('customer') extend {
  primary_key: c_custkey
  join_many: orders on orders.o_custkey = c_custkey
}
run: customers -> { aggregate: order_count is orders.count() }
```

- Malloy returns: 1,550,004 orders
- Right answer: 1,500,000 orders
- Worse: asked for the customers with no orders (`group_by: c_custkey`, `having: order_count = 0`),
  Malloy finds none; there are 50,004.

Generated SQL:

```sql
COUNT(1) as "order_count"
-- the same measure, with a second join_many in the query:
COUNT(DISTINCT orders_0."o_orderkey") as "order_count"
```

- Docs: [Aggregates](https://docs.malloydata.dev/documentation/language/aggregates): `join_name.count()`
  counts "the number of records appearing in a source", and "Local aggregation removes duplicate
  values"; [Joins](https://docs.malloydata.dev/documentation/language/join): aggregates "are always
  computed correctly regardless of join pattern".
- Upstream: [malloydata/malloy#1762](https://github.com/malloydata/malloy/issues/1762), open since
  July 2024, where Lloyd Tabb wrote "That should return 0. Sounds like a bug." A comment of 27
  September 2026 reproduces it on 0.0.434.

Works instead: `count(orders.o_orderkey)` returns 1,500,000:

```malloy
source: orders is duckdb.table('orders') extend { primary_key: o_orderkey }
source: customers is duckdb.table('customer') extend {
  primary_key: c_custkey
  join_many: orders on orders.o_custkey = c_custkey
}
run: customers -> { aggregate: order_count is count(orders.o_orderkey) }
```

**4. A `limit:` refinement drops the view's `order_by:`**

`by_clerk` sorts by clerk. `by_clerk + { limit: 3 }` sorts by the order count instead, Malloy's
default order, and returns the three busiest clerks. A `limit:` written in the view itself keeps
the order; one added with `+ { }` loses it, in a `nest:` too.

```malloy
source: orders is duckdb.table('orders') extend {
  view: by_clerk is { group_by: o_clerk; aggregate: order_count is count(); order_by: o_clerk }
}
run: orders -> by_clerk + { limit: 3 }
```

- Malloy returns: Clerk#000000542, #081, #901, the most orders first
- Right answer: Clerk#000000001, #002, #003, the view's order

Generated SQL:

```sql
ORDER BY 2 desc NULLS LAST
LIMIT 3
```

- Docs: [Views](https://docs.malloydata.dev/documentation/language/views): "The new view inherits the
  properties of the original, and adds new properties to it."
  [Ordering](https://docs.malloydata.dev/documentation/language/order_by): "When an `order_by:` is
  applied in a refinement, it will fully override whatever the previous ordering was."
- Upstream: reported as [malloydata/malloy#3137](https://github.com/malloydata/malloy/issues/3137)
  and fixed on main by [#3136](https://github.com/malloydata/malloy/pull/3136) (merged 7 October
  2026), which says the guard had been wrong since 0.0.218. No release has the fix yet.

Works instead: restate the order, `by_clerk + { order_by: o_clerk; limit: 3 }`:

```malloy
source: orders is duckdb.table('orders') extend {
  view: by_clerk is { group_by: o_clerk; aggregate: order_count is count(); order_by: o_clerk }
}
run: orders -> by_clerk + { order_by: o_clerk; limit: 3 }
```

**5. `having:` on a dimension empties `all()`**

The docs describe `having:` for conditions on aggregates. Malloy also accepts a condition on a
dimension there, without a warning, and moves it into the WHERE of the grouping-set query. There it
still reads the output column, which is NULL in the rows `all()` reads, so `is not null` or `=`
removes them and every share is NULL. A `!=` condition survives, because Malloy makes `!=` true on
NULL.

```malloy
run: duckdb.table('lineitem') -> {
  group_by: l_shipmode
  aggregate: lines is count(), share is count() / all(count())
  having: l_shipmode is not null
}
```

- Malloy returns: share is NULL for every ship mode
- Right answer: 0.143 for AIR, about a seventh for each mode
- Should be: a compile error that points to `where:`, or the guard the aggregate `having:` path
  already adds

Generated SQL:

```sql
WHERE (CASE WHEN group_set=1 THEN base."l_shipmode" END) IS NOT NULL
-- all() reads the group_set = 0 rows, which this WHERE removes
```

- Docs: [Views](https://docs.malloydata.dev/documentation/language/views): "Views may filter entire
  groupings based on aggregate values using the `having:` clause"; the
  [Quick Reference](https://docs.malloydata.dev/documentation/language/quick_reference): "Define a
  filter in a query based on the result of an aggregation".
- Upstream: reported as [malloydata/malloy#3163](https://github.com/malloydata/malloy/issues/3163).

Works instead: the same condition in `where:`, which returns 0.143 for AIR:

```malloy
run: duckdb.table('lineitem') -> {
  group_by: l_shipmode
  aggregate: lines is count(), share is count() / all(count())
  where: l_shipmode is not null
}
```

**6. `exclude()` of an outer dimension in a nest returns one group's count**

The docs say a nested query may name an outer dimension in `exclude()`, so `all_lines` should count
every line in every row. Unless the outer level has an `all()` or `exclude()` of its own, the outer
`l_returnflag` is never ungrouped: the SQL still groups that count by `l_returnflag` and spreads it
with `MAX`, so every row gets the count of the largest flag.

```malloy
run: duckdb.table('lineitem') -> {
  group_by: l_returnflag
  nest: by_mode is {
    group_by: l_shipmode
    aggregate: all_lines is exclude(count(), l_returnflag, l_shipmode)
  }
}
```

- Malloy returns: 3,043,852 in every row, the lines of flag N
- Right answer: 6,001,215, all lines
- Smaller: `exclude(count(), l_returnflag)` alone gives every flag's AIR row 435,291, flag N's AIR
  count; the right answer is 858,104.

Generated SQL:

```sql
MAX(CASE WHEN group_set=1 THEN COUNT(1) END) OVER () as "all_lines__2"
-- grouped by l_returnflag in every grouping set, so MAX picks the largest flag
```

- Docs: [Ungrouped Aggregates](https://docs.malloydata.dev/documentation/language/ungrouped-aggregates):
  "in a nested query, it is legal to name a grouping dimension from an outer query which contains
  the inner query."
- Code: an outer level gets its own grouping set only when it has an ungrouped aggregate, so
  `l_returnflag` is emitted ungated. Malloy's own test for this feature always has `all()` at the
  outer level, which hides the bug.
- Upstream: reported as [malloydata/malloy#3161](https://github.com/malloydata/malloy/issues/3161).

Right by accident: add `total is all(count())` to the outer level:

```malloy
run: duckdb.table('lineitem') -> {
  group_by: l_returnflag
  aggregate: total is all(count())
  nest: by_mode is {
    group_by: l_shipmode
    aggregate: all_lines is exclude(count(), l_returnflag, l_shipmode)
  }
}
```

## Compiles, then the SQL fails

**7. A join condition through the joined source's own join generates broken SQL**

Joining `lines` on `lines.orders.o_custkey` compiles, but the SQL uses the `orders` table in an ON
clause before it has joined `orders`. Malloy always joins a source's own joins after the source, so
no join order can satisfy this condition. A condition through a sibling join works.

```malloy
source: orders is duckdb.table('orders') extend { primary_key: o_orderkey }
source: lines is duckdb.table('lineitem') extend { join_one: orders with l_orderkey }
source: customers is duckdb.table('customer') extend {
  primary_key: c_custkey
  join_many: lines on lines.orders.o_custkey = c_custkey
}
run: customers -> { aggregate: line_count is lines.count() }
```

- DuckDB says: Binder Error: Referenced table "orders_0" not found!
- Should be: a compile error

Generated SQL:

```sql
LEFT JOIN (... FROM lineitem as x) AS lines_0
  ON orders_0."o_custkey"=base."c_custkey"
LEFT JOIN orders AS orders_0
  ON orders_0."o_orderkey"=lines_0."l_orderkey"
```

- Docs: [Joins](https://docs.malloydata.dev/documentation/language/join) shows `on` conditions over
  the source's and the joined source's own fields, and does not cover one that reaches further.
- Upstream: [malloydata/malloy#2486](https://github.com/malloydata/malloy/issues/2486) (open; a
  maintainer notes it "has never worked") and [#1482](https://github.com/malloydata/malloy/issues/1482)
  (open since November 2023). The reporter already asked for a compile error.

The same error comes from a condition that uses a dimension of the source itself, defined through
one of its own joins: `dimension: region is customers.c_region_name` then
`join_one: targets on targets.t_region = region`. Malloy joins `targets` before `customers`, although
`customers` is declared first. Writing the path out (`targets.t_region = customers.c_region_name`)
orders the joins correctly, even through a join of a join, so that is the workaround. 69 answers from
12 models failed with this error inside an `on` clause. Added to #2486 on 26 October 2026, with a
repro: [comment](https://github.com/malloydata/malloy/issues/2486#issuecomment-6419519243).

**8. DuckDB cannot bind Malloy's fan-out average of a `nullif()` dimension**

When a query fans out, Malloy computes `avg()` and `sum()` on DuckDB in a correlated subquery over
`{key, val}` structs. The SQL is valid, but DuckDB cannot bind a struct value that is a DuckDB macro
reading an outer column, and DuckDB implements `NULLIF` as a macro.

```malloy
source: orders is duckdb.table('orders') extend {
  primary_key: o_orderkey
  join_many: lines is duckdb.table('lineitem') on lines.l_orderkey = o_orderkey
  dimension: price is nullif(o_totalprice, 0)
}
run: orders -> { aggregate: avg_price is price.avg(), line_count is lines.count() }
```

- DuckDB says: Binder Error: Need named argument for struct pack, e.g. STRUCT_PACK(a := b)
- Expected: avg_price 151,219.54, line_count 6,001,215
- Without Malloy, on DuckDB 1.4.4 to 1.5.6:
  `SELECT (SELECT {v: NULLIF(t.x, 0)}) FROM (VALUES (1), (2)) t(x);` fails the same way.

So this is DuckDB's bug to fix. Malloy could avoid it by writing `nullif` as `CASE`, as it already
does for `pick`. The [Functions](https://docs.malloydata.dev/documentation/language/functions) page
lists `nullif` but recommends `pick`.

Works instead: `o_totalprice ? pick null when 0`, the docs' replacement for `nullif`:

```malloy
source: orders is duckdb.table('orders') extend {
  primary_key: o_orderkey
  join_many: lines is duckdb.table('lineitem') on lines.l_orderkey = o_orderkey
  dimension: price is o_totalprice ? pick null when 0
}
run: orders -> { aggregate: avg_price is price.avg(), line_count is lines.count() }
```

## Errors that don't say what's wrong

For an AI client the message is the only hint it gets.

**9. `~` with a time or number range crashes the compiler**

The docs give `event_time ~ @2003` as a filter. The compiler has no `~` case for a range, so every
range on the right of `~` (a time literal, `@1995 to @1996`, `10 to 20`) stops with an internal
error.

```malloy
run: duckdb.table('lineitem') -> {
  where: l_shipdate ~ @1995
  aggregate: lines is count()
}
```

- Malloy says: Internal compiler error (likely a Malloy bug ... please file an issue): mysterious
  error in range computation
- Expected: 914,963 lines

- Docs: [Filters](https://docs.malloydata.dev/documentation/language/filters), under Ranges: "The
  `~` operator will check to see if a value is within a range", with `event_time ~ @2003`
  ("`event_time` occurs within the year 2003") and `size ~ 10 to 20`.
- Code: `Range.apply` handles `=`, `!=`, `<`, `<=`, `>` and `>=`, and throws for anything else. The
  same on main.
- Upstream: reported as [malloydata/malloy#3162](https://github.com/malloydata/malloy/issues/3162).

Works instead: `l_shipdate ? @1995`, or the filter expression `l_shipdate ~ f'1995'`, both 914,963:

```malloy
run: duckdb.table('lineitem') -> {
  where: l_shipdate ? @1995
  aggregate: lines is count()
}
```

**10. Subtracting two dates gives an error about a logger**

Malloy does not document subtracting two dates; it measures the gap with `days(a to b)`. But
`avg(l_shipdate - l_commitdate)` is a natural first try, and the compiler's own error for it is
lost: the error is logged on a node the compiler built and never attached, which has no logger. In
a `where:` the same mistake reports an internal compiler error.

```malloy
run: duckdb.table('lineitem') -> {
  aggregate: days_late is avg(l_shipdate - l_commitdate)
}
```

- Malloy says: Cannot define 'days_late', Attempted to access logger without a translator
- Better: an error that points to `days(l_commitdate to l_shipdate)`
- In MalloyBench: 27 one-shot answers failed with exactly this error, from 13 model settings. With
  the compiler in the loop, 41 answers ran into it: 42% of the queries written right after it hit
  it again, 9 answers never got past it, and only 6 ever found `days()`.

- Docs: [Timestamp and Date Operations](https://docs.malloydata.dev/documentation/language/timestamp-operations):
  "Add or subtract a duration from a timestamp or date using `+` or `-` with a number and time
  unit"; [Expressions](https://docs.malloydata.dev/documentation/language/expressions): "To measure
  the difference between two times, pass a range expression to one of the extraction functions."
- Code: `delta()` in `lang/ast/types/expression-def.ts` reads a date minus anything but a duration
  as an offset in days, and wraps the right side in an `ExprDuration` it never attaches to the
  tree. The same on main.
- Upstream: reported as item 1 of [malloydata/malloy#3164](https://github.com/malloydata/malloy/issues/3164).

Works instead: `days(l_commitdate to l_shipdate)`, 0.986 days:

```malloy
run: duckdb.table('lineitem') -> {
  aggregate: days_late is avg(days(l_commitdate to l_shipdate))
}
```

## A modeling trap

Not a bug: a model that looks reasonable and counts wrong. A lint would catch it.

**11. A primary key built with `concat()` counts the unmatched row**

Malloy counts through a join by counting distinct keys, which works when the key is NULL on the
empty row a left join adds. DuckDB's `concat()` treats NULL as an empty string, so the key
`concat(ps_partkey::string, '-', ps_suppkey::string)` is `'-'` on that row, and the distinct count
includes it.

```malloy
source: partsupp is duckdb.table('partsupp') extend {
  primary_key: ps_key
  dimension: ps_key is concat(ps_partkey::string, '-', ps_suppkey::string)
}
source: parts is duckdb.table('part') extend {
  primary_key: p_partkey
  join_many: big_stock is partsupp on big_stock.ps_partkey = p_partkey and big_stock.ps_availqty > 9990
  join_many: big_lines is duckdb.table('lineitem') on big_lines.l_partkey = p_partkey and big_lines.l_quantity > 49
}
run: parts -> { aggregate: offers is big_stock.count(), lines is big_lines.count() }
```

- Malloy returns: 719 offers
- Right answer: 718 offers

The [Functions](https://docs.malloydata.dev/documentation/language/functions) page documents
`concat()`'s NULL handling per database, and on BigQuery the same model counts 718. A key built
with `coalesce()` fails the same way; a text key cast from a number,
`(ps_partkey * 100000 + ps_suppkey)::string`, stays NULL and counts right. A lint for primary keys
that are not NULL when the columns they read are NULL would catch it. (The second `join_many` is
what makes Malloy count distinct keys here; with `big_stock` alone, issue 3 makes the count wrong
for any key.)

Counts right: an arithmetic key, `ps_partkey * 100000 + ps_suppkey`:

```malloy
source: partsupp is duckdb.table('partsupp') extend {
  primary_key: ps_key
  dimension: ps_key is ps_partkey * 100000 + ps_suppkey
}
source: parts is duckdb.table('part') extend {
  primary_key: p_partkey
  join_many: big_stock is partsupp on big_stock.ps_partkey = p_partkey and big_stock.ps_availqty > 9990
  join_many: big_lines is duckdb.table('lineitem') on big_lines.l_partkey = p_partkey and big_lines.l_quantity > 49
}
run: parts -> { aggregate: offers is big_stock.count(), lines is big_lines.count() }
```

## Rules that trip AI models most

Not bugs: each is a documented choice, and these are the rules models break most. Counts are failed
answers in MalloyBench v0.1's single-shot runs (one answer, no compiler) over the 11 models that
completed it.

**12. `where:` needs commas between conditions, `group_by:` does not**

Models write `where:` one condition per line, the way `group_by:` and `aggregate:` take one item per
line, and the parser stops at the second condition.

```malloy
run: duckdb.table('lineitem') -> {
  where:
    l_receiptdate > l_commitdate
    l_shipdate >= @1995-01-01
  aggregate: late_lines is count()
}
```

- Malloy says: no viable alternative at input 'l_shipdate'
- A friendlier message: say that conditions in `where:` need commas. Malloy already rewrites some
  parser errors this way ("Did you mean 'group_by:'?").
- In MalloyBench: 88 failed answers from 8 of the 11 models. With Malloy's language reference in
  context: 203. The reference shows `aggregate:` one item per line and mentions the commas once, in
  prose; none of its examples has a `where:` with two conditions.

- Docs: [Filters](https://docs.malloydata.dev/documentation/language/filters): "The comma-separated
  list of filters are `and`ed together, so `where: x, y` is equivalent to `where: x and y`."
- Upstream: dropping the commas is [malloydata/malloy#465](https://github.com/malloydata/malloy/issues/465),
  open since April 2022, where a maintainer explains that the comma "is very important in
  disambiguating the boundaries between expressions".

Works: a comma between the conditions:

```malloy
run: duckdb.table('lineitem') -> {
  where:
    l_receiptdate > l_commitdate,
    l_shipdate >= @1995-01-01
  aggregate: late_lines is count()
}
```

**13. `count(distinct x)` is an error**

Malloy's `count(x)` already counts distinct values, and the error names the fix. It is still the SQL
habit models reach for first.

```malloy
run: duckdb.table('lineitem') -> { aggregate: modes is count(distinct l_shipmode) }
```

- Malloy says: count(distinct expression) deprecated, use count(expression) instead.
- In MalloyBench: 114 failed answers from 8 of the 11 models.

- Docs: [Malloy 4.0 messages](https://docs.malloydata.dev/documentation/language/m4warnings): "The
  SQL syntax for distinct counts `count(distinct <<expression>>)` is deprecated in favor of
  `count(<<expression>>)`." It became an error with Malloy 4.0 (PR #1422, October 2023). Accepting
  it again with a warning, as the 4.0 transition did, would reverse that decision; the message could
  say "not supported" rather than "deprecated".

Works: `count(l_shipmode)`:

```malloy
run: duckdb.table('lineitem') -> { aggregate: modes is count(l_shipmode) }
```

**14. `d.year = 1995` compares a date to a number**

`.year` truncates a date to its year: `l_shipdate.year` is 1995-01-01, not 1995. Comparing a date to
a string, `d >= '1995-01-01'`, fails the same way.

```malloy
run: duckdb.table('lineitem') -> {
  where: l_shipdate.year = 1995
  aggregate: lines is count()
}
```

- Malloy says: Cannot compare a date to a number
- A friendlier message: name `year(d)` and `@1995` in the error
- In MalloyBench: 61 failed answers, number and string comparisons together, from 8 of the 11 models.

- Docs: [Timestamp and Date Operations](https://docs.malloydata.dev/documentation/language/timestamp-operations):
  "For truncation to a time unit (timeframe), use the period (`.`) operator followed by the desired
  timeframe."

Works: `l_shipdate ? @1995`:

```malloy
run: duckdb.table('lineitem') -> {
  where: l_shipdate ? @1995
  aggregate: lines is count()
}
```

## Errors that send models in circles

We went through every compiler error in MalloyBench's agentic runs, where models compile, run and
retry. Most were fixed on the next attempt. The ones models could not get past were mostly those
where the message points away from the cause: item 10, and these five. Counts are agentic answers
that got the message, out of the 3,625 in the v0.1 and v0.2 reports.

**15. In a restricted query, an unknown function suggests the call restricted mode rejects**

MalloyBench compiles every answer with `loadRestrictedQuery`, which rejects SQL function calls
written `name!(...)`. The error for a function Malloy does not have suggests exactly that call. A
restricted query cannot read `duckdb.table()` either, so this one runs against a model holding
`source: lineitem is duckdb.table('lineitem')`:

```malloy
run: lineitem -> { aggregate: median_quantity is median(l_quantity) }
```

- Malloy says: Unknown function 'median'. Use 'median!(...)' to call a SQL function directly.
- Then, for `median!(l_quantity)`: `median!(...)` cannot be used in a restricted query ... direct
  SQL function calls (`!type(...)`) are not permitted.
- Better: no hint in a restricted query, or the link to the function reference that the parser's
  own unknown-function message gives
- In MalloyBench: 66 answers followed the hint into the second error.

- Code: `findFunctionDef` in `lang/ast/expressions/expr-func.ts` adds the hint without checking
  `isRestricted()`. The same on main.
- Upstream: reported as item 2 of [malloydata/malloy#3164](https://github.com/malloydata/malloy/issues/3164).
  Malloy has no median or percentile function to suggest instead
  ([#1555](https://github.com/malloydata/malloy/issues/1555), open since 2023).

**16. `project:` reports a missing colon**

`project:` became `select:` in Malloy 4.0. The error for a view with no fields still lists
`project` as a view type, and `project:` then gets a message about a colon that is there.

```malloy
run: duckdb.table('lineitem') -> {
  project: l_shipmode
  limit: 3
}
```

- Malloy says: Expected ':' following 'project'
- And with `limit: 3` alone: Can't determine view type (`group_by` / `aggregate` / `nest`,
  `project`, `index`)
- Better: "The 'project:' keyword is no longer supported. Use 'select:' instead.", which Malloy
  said until June 2026
- In MalloyBench: 116 answers got the colon error, 53 of them after the view-type message had named
  `project`.

- Docs: [Malloy 4.0 messages](https://docs.malloydata.dev/documentation/language/m4warnings): "The
  `project:` keyword has been renamed to `select:`."
- Code: PR [#2457](https://github.com/malloydata/malloy/pull/2457) (July 2025) added that message,
  among others for AI authors. PR [#2882](https://github.com/malloydata/malloy/pull/2882) (June
  2026) dropped the `PROJECT` token, and the message with it, so `project` now matches a generic
  "Expected ':'" rule. The same on main.
- Upstream: reported as item 3 of [malloydata/malloy#3164](https://github.com/malloydata/malloy/issues/3164).

Works instead: `select:`:

```malloy
run: duckdb.table('lineitem') -> {
  select: l_shipmode
  limit: 3
}
```

**17. An aggregate cannot use another aggregate of the same query**

```malloy
run: duckdb.table('lineitem') -> {
  aggregate:
    lines is count()
    late_lines is count() { where: l_receiptdate > l_commitdate }
    late_share is late_lines / lines
}
```

- Malloy says: 'late_lines' is not defined; 'lines' is not defined; Cannot use a scalar field in an
  aggregate operation, did you mean to use a group_by or select operation instead?
- With `late_share` in `calculate:`: Cannot use an aggregate field in a calculate operation, did you
  mean to use an aggregate operation instead?
- In the same query, `having: late_lines / lines > 0.6` compiles, with both definitions inlined.
- Better: say that `aggregate:` cannot read the query's own outputs, and suggest repeating the
  expression or declaring a measure in the query's `extend:`
- In MalloyBench: 208 answers.

- Upstream: [malloydata/malloy#2276](https://github.com/malloydata/malloy/issues/2276), open since
  April 2025, where a maintainer writes "It feels like this should work"; the scalar message is
  [#1947](https://github.com/malloydata/malloy/issues/1947). Item 4 of
  [malloydata/malloy#3164](https://github.com/malloydata/malloy/issues/3164) reports the messages.

Works instead: the same measures declared in the query's `extend:`, 0.632:

```malloy
run: duckdb.table('lineitem') -> {
  extend: {
    measure:
      lines is count()
      late_lines is count() { where: l_receiptdate > l_commitdate }
  }
  aggregate: lines, late_lines, late_share is late_lines / lines
}
```

**18. A `#` note at the end of a query block reports an "unimplemented" statement**

`#` starts an annotation, not a comment, so a note after the last field is an error. The message
names an internal element type and misspells "encountered".

```malloy
run: duckdb.table('lineitem') -> {
  group_by: l_shipmode
  aggregate: lines is count() # number of lines
}
```

- Malloy says: Parser enountered unexpected statement type 'unimplemented' when it needed 'query
  statement'
- Better: "Object annotation not connected to any object", what the same line gets at the end of a
  document
- In MalloyBench: 23 answers, each with a note the model wrote to itself; none hit it twice in a
  row.

- Code: the grammar allows an annotation as a query statement, and `MalloyToAST` has no visitor for
  it. The same on main.
- Upstream: not reported; left out of [malloydata/malloy#3164](https://github.com/malloydata/malloy/issues/3164) as minor.

Works instead: a comment, `//`:

```malloy
run: duckdb.table('lineitem') -> {
  group_by: l_shipmode
  aggregate: lines is count() // number of lines
}
```

**19. `&` or `|` between two conditions reports "Alternation tree has no value"**

`&` and `|` combine partial conditions, as in `l_quantity ? > 10 & < 20`. They bind tighter than
`=`, so between two whole conditions the left part becomes an alternation, which has no value.

```malloy
run: duckdb.table('lineitem') -> {
  where: (l_receiptdate > l_commitdate) & l_shipmode = 'AIR'
  aggregate: late_air_lines is count()
}
```

- Malloy says: Alternation tree has no value, and Filter expression must have boolean value
- Better: say that `and` and `or` combine whole conditions
- In MalloyBench: 11 answers; 7 of the 20 queries written right after it got it again.

- Docs: [Expressions](https://docs.malloydata.dev/documentation/language/expressions): "Conditions
  can be logically combined with the two alternation operators, `&` and `|`. These are different
  from `and` and `or` in that they operate on conditions which return boolean values, rather than
  boolean values directly."
- Upstream: [malloydata/malloy#1083](https://github.com/malloydata/malloy/issues/1083), open since
  April 2023, asks for helpful messages when `&` and `|` are misused. We have not added this case to it.

Works instead: `and`, 542,360 lines:

```malloy
run: duckdb.table('lineitem') -> {
  where: l_receiptdate > l_commitdate and l_shipmode = 'AIR'
  aggregate: late_air_lines is count()
}
```

## Checked, and not a bug

`where: x != 0` keeps the rows where `x` is NULL, unlike SQL. Two of the agents that solved
MalloyBench's questions blind flagged it as a trap. It is documented:
[Null Handling](https://docs.malloydata.dev/documentation/language/null-handling) shows Malloy's
`!=` returning true for `1 != null` and `null != null`, so a comparison that excludes a value keeps
the rows that have none.

## Small fixes to the docs

- [Expressions](https://docs.malloydata.dev/documentation/language/expressions): the operator list
  does not mention `!~`; the NULL section refers to `~!`.
- [Aggregates](https://docs.malloydata.dev/documentation/language/aggregates) lists
  `join_name.field.count()` as a distinct count, but 0.0.435 rejects `orders.o_orderkey.count()`
  ("is not a source or join"); `count(orders.o_orderkey)` works.
- [Functions](https://docs.malloydata.dev/documentation/language/functions) lists `nullif()`, and
  further down says "The `NULLIF` SQL function is not available in Malloy".
- [Timestamp and Date Operations](https://docs.malloydata.dev/documentation/language/timestamp-operations):
  the table of extraction functions leaves out `year()` and `month()`.
- [Filters](https://docs.malloydata.dev/documentation/language/filters): the example
  `size:  10 to 100` uses the pre-4.0 syntax and no longer compiles.
