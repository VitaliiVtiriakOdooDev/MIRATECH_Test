# Delta group consolidation — Odoo 17

This is a prototype for the fictional Delta scenario. The task does not specify an Odoo version; this implementation assumes Odoo Community 17 and PostgreSQL. The addon adds a month-end snapshot, an elimination journal entry in a separate company, and a report by account type. It does not alter operating-company entries or Odoo's standard Profit and Loss. Amounts use debit-positive signs; revenue and liabilities normally show negative values.

## Run

With Docker Compose installed, run `./setup-demo.sh`, then open http://localhost:8069, select database `delta_demo` and sign in as `admin` / `admin`. Demo credentials are for local use only. The command creates a database and starts a web server; it does not reset existing data. The demo uses posted USD customer invoices, vendor bills, linked partial credit notes and Odoo payments for intercompany transactions; external sales, expenses and the loan use posted general journal entries. For a separate fresh database without deleting an existing one, run `DELTA_DB=delta_new ./setup-demo.sh` and select `delta_new`. The setup builds the `delta-consolidation:17.0` image with the addon and checks the demo numbers. To run the addon test and repeat the integration verification:

```
docker compose run --rm --no-deps odoo odoo -d delta_demo -u delta_consolidation --test-enable --test-tags /delta_consolidation --stop-after-init
docker compose run --rm --no-deps -T odoo odoo shell -d delta_demo < verify-demo.py
ruff check . && ruff format --check .
```

The addon can also be copied to an Odoo 17 addons path and installed with its `account` dependency. For a new dataset, create a separate USD elimination company, a general journal and clearing account, and accounts for every account type used by intercompany transactions. Select the operating companies and elimination company in Odoo's company switcher. Accounts for non-trade intercompany balances such as loans must have **Eliminate intercompany balances** checked; counterparties must use the company partner (or its commercial partner).

## Controller: five checks

1. In the company switcher enable all four Delta companies. Open **Accounting → Group consolidation** and select **Demo March 2026**.
2. Read rows with a company name for that company's local amounts and USD equivalents; rows with no company are the group. Income and expense are for March; balance sheet rows are cumulative through March, with earlier profit in `equity_unaffected` and the current month's result in `equity_current_result`. The latter repeats the P&L net result for balance-sheet presentation; do not add it to the P&L rows.
3. Check group March `income` is -300,000 USD and `expense` is 120,000 USD. These reflect three companies' external sales and costs only.
4. Open the linked **Journal Entry** and inspect its posted lines. Use **Elimination source entries** to open the underlying entries. The 20,000 USD clearing debit represents the Poland payment in transit; Ukraine's March invoice is eliminated even though the US books it in April.
5. Switch to each operating company and open its standard Profit and Loss for March. Compare its books with its snapshot row; the elimination journal belongs solely to the separate elimination company.

## Method and limitations

The engine uses posted `account.move.line` balances, Odoo company/currency conversion, account types, company partners and a posted `account.move` in a separate company. All items are translated at the selected month-end rate, including income and equity. This deliberately simplified policy is not an IFRS translation method; it does not calculate historical equity, average-rate income or a separate cumulative translation adjustment. Prior-period P&L is reclassified to retained earnings in the report. The elimination entry reverses intercompany income, expenses, trade balances, and marked loan balances; its balancing line is a timing/translation clearing account. Review and reconcile the clearing account before relying on figures.

Snapshots are cumulative and independent: the linked journal entry is the complete adjustment as of that date, not an incremental monthly posting. Do not sum elimination-company journal entries from multiple snapshots as a ledger; the snapshot report uses only its own entry. Recreate a snapshot after source changes. If the linked journal entry is reversed or edited independently, the snapshot is not automatically invalidated; investigate and generate a replacement. The current implementation aggregates by account type, links source journal entries but does not match invoices to payments or provide source-line-level drill-down, and does not distinguish FX differences from timing differences. It assumes all transactions with an operating company's commercial partner in the relevant accounts are internal. It requires all selected companies to be enabled; grant the Group Consolidation Controller role only to trusted users with access to every group company. The role can read all snapshots; it is not isolated per company. No taxes, minority interests, consolidation ownership percentages or unrealised profit are modelled. This is not production-ready consolidation software.

## AI and verification

The addon, demo and documentation were drafted with an AI coding agent. Verification should include the addon tests, the five controller checks, inspection of source journal entries and a review of any nonzero clearing balance. See `DECISIONS.md` and `ASSUMPTIONS.md`.
