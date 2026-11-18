"""Run inside Odoo shell after loading demo; all verification writes are rolled back."""

from datetime import date

from odoo import Command

usd = env.ref("base.USD")
companies = env["res.company"].search(
    [("name", "in", ["Delta US Inc.", "Delta Ukraine LLC", "Delta Poland sp. z o.o."])]
)
assert len(companies) == 3
us = companies.filtered(lambda c: c.name == "Delta US Inc.")
ua = companies.filtered(lambda c: c.name == "Delta Ukraine LLC")
pl = companies.filtered(lambda c: c.name == "Delta Poland sp. z o.o.")
elim = env["res.company"].search([("name", "=", "Delta Group Eliminations")])
env = env(context=dict(env.context, allowed_company_ids=(companies | elim).ids))

template = env["delta.consolidation"].search([("name", "=", "Demo March 2026")])
assert len(template) == 1
march = env["delta.consolidation"].create(
    {
        "name": "March verification",
        "date_end": "2026-03-31",
        "company_ids": [Command.set(companies.ids)],
        "elimination_company_id": elim.id,
        "journal_id": template.journal_id.id,
        "clearing_account_id": template.clearing_account_id.id,
    }
)
march.action_generate()
assert march.move_id.state == "posted"
group = {line.account_type: line.amount for line in march.line_ids if not line.company_id}
assert group["income"] == -300000 and group["expense"] == 120000
assert group["equity_current_result"] == -180000
assert group["asset_cash"] == 520000 and group["asset_current"] == 20000
assert group["asset_receivable"] == group["liability_payable"] == 0
assert group["liability_current"] == 0
assert group["equity_unaffected"] == -360000
for company, income, expense in [
    (us, -100000, 70000),
    (ua, -6000000, 1600000),
    (pl, -520000, 160000),
]:
    local = {
        line.account_type: line.local_amount
        for line in march.line_ids
        if line.company_id == company
    }
    assert local["income"] == income and local["expense"] == expense, (company.name, local)

moves = env["account.move"]
ua_invoice = moves.search(
    [
        ("company_id", "=", ua.id),
        ("move_type", "=", "out_invoice"),
        ("invoice_date", "=", "2026-03-31"),
        ("amount_total", "=", 50000),
        ("partner_id", "=", us.partner_id.id),
    ]
)
us_bill = moves.search(
    [
        ("company_id", "=", us.id),
        ("move_type", "=", "in_invoice"),
        ("invoice_date", "=", "2026-03-31"),
        ("amount_total", "=", 50000),
        ("partner_id", "=", ua.partner_id.id),
    ]
)
assert len(ua_invoice) == len(us_bill) == 1
assert ua_invoice.date == date(2026, 3, 31) and us_bill.date == date(2026, 4, 2)
assert ua_invoice.currency_id == us_bill.currency_id == usd
assert ua_invoice in march.source_move_ids and us_bill not in march.source_move_ids
credit = moves.search(
    [
        ("company_id", "=", pl.id),
        ("move_type", "=", "out_refund"),
        ("amount_total", "=", 5000),
        ("state", "=", "posted"),
    ]
)
assert len(credit) == 1 and credit.currency_id == usd and credit in march.source_move_ids
assert (
    credit.reversed_entry_id.amount_total == 30000
    and credit.reversed_entry_id.invoice_date == date(2026, 2, 28)
)
payments = env["account.payment"].search([("ref", "=", "Poland payment in transit")])
assert len(payments) == 2
assert payments.filtered(lambda p: p.company_id == us).date == date(2026, 3, 31)
assert payments.filtered(lambda p: p.company_id == pl).date == date(2026, 4, 1)
assert all(p.amount == 20000 and p.currency_id == usd and p.state == "posted" for p in payments)

april = env["delta.consolidation"].create(
    {
        "name": "April verification",
        "date_end": "2026-04-30",
        "company_ids": [Command.set(companies.ids)],
        "elimination_company_id": elim.id,
        "journal_id": march.journal_id.id,
        "clearing_account_id": march.clearing_account_id.id,
    }
)
april.action_generate()
april_group = {line.account_type: line.amount for line in april.line_ids if not line.company_id}
assert april_group.get("asset_current", 0) == 0, april_group
assert april_group["asset_cash"] == 540000 and april_group["equity_unaffected"] == -540000
assert april_group.get("income", 0) == april_group.get("expense", 0) == 0
env.cr.rollback()
print(
    "PASS: posted documents, currencies, credit note, loan, payment timing, March and April group figures"
)
