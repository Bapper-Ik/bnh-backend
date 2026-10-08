# Authority Policy v1

`policy.py` uses exact decimal strings and policy identifier `bnh-doa-v1`.

| Amount (NGN) | Ordinary staff authority |
| --- | --- |
| 1 through 5,000,000 | Own department HOD |
| Above 5,000,000 through 100,000,000 | Chief of Staff |
| Above 100,000,000 through 500,000,000 | Managing Director |
| Above 500,000,000 | Board |

The requester's current offices set a minimum: HOD → Chief of Staff; Chief of Staff → MD; MD → Board. Use the higher of this minimum and the amount band. Multiple appointments cannot lower the result. No sequential approval chain or editable threshold exists.

`calculate_lines` accepts positive quantities with up to four decimal places and nonnegative unit prices with up to two. Each line rounds HALF_UP to two places before summation; totals cannot exceed the database's NUMERIC(17,2). API values use plain decimal strings, never floats or exponent notation.

The requisition service obtains appointments from trusted organisation records, checks current scoped eligibility, rejects missing/ambiguous assignments and self-approval, and freezes the policy, route and office context with the submitted revision. Board routing requires distinct Secretary/Chairman people and a Chairman different from the requester; it creates an awaiting-resolution record, not a Board decision.

Run `uv run pytest tests/authority tests/requisitions` with an isolated PostgreSQL `.env.test`. Parameterised tests cover all requester bands, exact kobo boundaries, multiple-office floors, invalid values and the sample ₦71,640 total. Production reads and writes use the same database URL per environment; tests never use Render data.
