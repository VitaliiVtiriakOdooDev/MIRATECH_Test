# Run with: odoo shell -d delta_demo < demo.py
from datetime import date

from odoo import Command

if env["delta.consolidation"].search_count([("name", "=", "Demo March 2026")]):
    print("Demo already loaded")
else:
    usd = env.ref("base.USD")
    uah = env.ref("base.UAH")
    pln = env.ref("base.PLN")
    (usd | uah | pln).write({"active": True})
    us = env.company
    us.write({"name": "Delta US Inc.", "currency_id": usd.id})
    ua = env["res.company"].create({"name": "Delta Ukraine LLC", "currency_id": uah.id})
    pl = env["res.company"].create({"name": "Delta Poland sp. z o.o.", "currency_id": pln.id})
    elim = env["res.company"].create({"name": "Delta Group Eliminations", "currency_id": usd.id})
    env.user.company_ids |= ua | pl | elim
    env = env(context=dict(env.context, allowed_company_ids=(us | ua | pl | elim).ids))
    companies = [us, ua, pl]
    multipliers = {us.id: 1, ua.id: 40, pl.id: 4}
    for currency, rate in [(usd, 1), (uah, 40), (pln, 4)]:
        env["res.currency.rate"].create(
            {"currency_id": currency.id, "name": "2026-01-01", "rate": rate, "company_id": False}
        )
    accounts, journals, sales_journals, purchase_journals, bank_journals = {}, {}, {}, {}, {}
    specs = [
        ("cash", "100100", "asset_cash"),
        ("ar", "110100", "asset_receivable"),
        ("loan_ar", "120100", "asset_current"),
        ("clearing", "120200", "asset_current"),
        ("ap", "200100", "liability_payable"),
        ("loan_ap", "210100", "liability_current"),
        ("retained", "300100", "equity_unaffected"),
        ("sales", "400100", "income"),
        ("cost", "600100", "expense"),
    ]
    for company in companies + [elim]:
        accounts[company.id] = {}
        for key, code, kind in specs:
            existing = (
                env["account.account"]
                .with_company(company)
                .search([("company_id", "=", company.id), ("account_type", "=", kind)], limit=1)
                if key == "retained"
                else False
            )
            accounts[company.id][key] = existing or env["account.account"].with_company(
                company
            ).create(
                {
                    "name": key,
                    "code": "D" + code,
                    "account_type": kind,
                    "company_id": company.id,
                    "reconcile": key in ("ar", "ap"),
                    "delta_intercompany": key in ("loan_ar", "loan_ap"),
                }
            )
        journals[company.id] = (
            env["account.journal"]
            .with_company(company)
            .create(
                {
                    "name": "Demo journal",
                    "code": "DEMO",
                    "type": "general",
                    "company_id": company.id,
                }
            )
        )
        if company != elim:
            sales_journals[company.id] = (
                env["account.journal"]
                .with_company(company)
                .create(
                    {
                        "name": "Demo Sales",
                        "code": "DSAL",
                        "type": "sale",
                        "company_id": company.id,
                        "default_account_id": accounts[company.id]["sales"].id,
                    }
                )
            )
            purchase_journals[company.id] = (
                env["account.journal"]
                .with_company(company)
                .create(
                    {
                        "name": "Demo Purchases",
                        "code": "DPUR",
                        "type": "purchase",
                        "company_id": company.id,
                        "default_account_id": accounts[company.id]["cost"].id,
                    }
                )
            )
            bank_journals[company.id] = (
                env["account.journal"]
                .with_company(company)
                .create(
                    {
                        "name": "Demo Bank",
                        "code": "DBNK",
                        "type": "bank",
                        "company_id": company.id,
                        "default_account_id": accounts[company.id]["cash"].id,
                    }
                )
            )
            for method in (
                bank_journals[company.id].inbound_payment_method_line_ids
                | bank_journals[company.id].outbound_payment_method_line_ids
            ):
                method.payment_account_id = accounts[company.id]["cash"]
            for partner in (us | ua | pl).partner_id:
                partner.with_company(company).write(
                    {
                        "property_account_receivable_id": accounts[company.id]["ar"].id,
                        "property_account_payable_id": accounts[company.id]["ap"].id,
                    }
                )

    def post(company, when, label, debit, credit, amount, partner=None):
        amount *= multipliers[company.id]
        account = accounts[company.id]
        m = (
            env["account.move"]
            .with_company(company)
            .create(
                {
                    "journal_id": journals[company.id].id,
                    "date": when,
                    "ref": label,
                    "line_ids": [
                        Command.create(
                            {
                                "name": label,
                                "account_id": account[debit].id,
                                "partner_id": partner.id if partner else False,
                                "debit": amount,
                            }
                        ),
                        Command.create(
                            {
                                "name": label,
                                "account_id": account[credit].id,
                                "partner_id": partner.id if partner else False,
                                "credit": amount,
                            }
                        ),
                    ],
                }
            )
        )
        m.action_post()

    def invoice(
        company,
        partner,
        invoice_date,
        accounting_date,
        amount,
        move_type,
        label,
        reversed_entry=None,
    ):
        sales = move_type in ("out_invoice", "out_refund")
        journal = (sales_journals if sales else purchase_journals)[company.id]
        move = (
            env["account.move"]
            .with_company(company)
            .create(
                {
                    "move_type": move_type,
                    "partner_id": partner.id,
                    "currency_id": usd.id,
                    "invoice_date": invoice_date,
                    "date": accounting_date,
                    "journal_id": journal.id,
                    "ref": label,
                    "reversed_entry_id": reversed_entry.id if reversed_entry else False,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": label,
                                "quantity": 1,
                                "price_unit": amount,
                                "account_id": accounts[company.id]["sales" if sales else "cost"].id,
                                "tax_ids": [Command.clear()],
                            }
                        )
                    ],
                }
            )
        )
        move.action_post()
        return move

    def payment(company, partner, when, amount, direction, partner_type):
        bank = bank_journals[company.id]
        method = (
            bank.outbound_payment_method_line_ids
            if direction == "outbound"
            else bank.inbound_payment_method_line_ids
        )[:1]
        payment_record = (
            env["account.payment"]
            .with_company(company)
            .create(
                {
                    "partner_id": partner.id,
                    "partner_type": partner_type,
                    "payment_type": direction,
                    "amount": amount,
                    "currency_id": usd.id,
                    "date": when,
                    "journal_id": bank.id,
                    "payment_method_line_id": method.id,
                    "ref": "Poland payment in transit",
                }
            )
        )
        payment_record.action_post()
        return payment_record

    post(us, "2026-01-15", "Loan to Ukraine USD 200,000", "loan_ar", "cash", 200000, ua.partner_id)
    post(ua, "2026-01-15", "Loan from US USD 200,000", "cash", "loan_ap", 200000, us.partner_id)
    for month in (1, 2, 3):
        end = date(2026, month, [31, 28, 31][month - 1]).isoformat()
        for seller, amount in ((ua, 50000), (pl, 30000)):
            label = "Intercompany services %s %s USD %s" % (seller.name, end, amount)
            seller_invoice = invoice(seller, us.partner_id, end, end, amount, "out_invoice", label)
            buyer_bill = invoice(
                us,
                seller.partner_id,
                end,
                "2026-04-02" if seller == ua and month == 3 else end,
                amount,
                "in_invoice",
                label,
            )
            if seller == pl and month == 2:
                poland_february_invoice, us_february_bill = seller_invoice, buyer_bill
        for c in companies:
            post(c, end, "External sales " + end, "cash", "sales", 100000)
            post(c, end, "External costs " + end, "cost", "cash", 40000)
    invoice(
        pl,
        us.partner_id,
        "2026-02-28",
        "2026-02-28",
        5000,
        "out_refund",
        "Poland partial credit note USD 5000",
        reversed_entry=poland_february_invoice,
    )
    invoice(
        us,
        pl.partner_id,
        "2026-02-28",
        "2026-02-28",
        5000,
        "in_refund",
        "Poland partial credit note USD 5000",
        reversed_entry=us_february_bill,
    )
    payment(us, pl.partner_id, "2026-03-31", 20000, "outbound", "supplier")
    payment(pl, us.partner_id, "2026-04-01", 20000, "inbound", "customer")
    for month in (1, 2, 3):
        end = date(2026, month, [31, 28, 31][month - 1])
        run = env["delta.consolidation"].create(
            {
                "name": "Demo %s 2026" % end.strftime("%B"),
                "date_end": end,
                "company_ids": [Command.set([c.id for c in companies])],
                "elimination_company_id": elim.id,
                "journal_id": journals[elim.id].id,
                "clearing_account_id": accounts[elim.id]["clearing"].id,
            }
        )
        run.action_generate()
        group = {line.account_type: line.amount for line in run.line_ids if not line.company_id}
        assert group["income"] == -300000 and group["expense"] == 120000, group
        assert group.get("asset_receivable", 0) == 0 and group.get("liability_payable", 0) == 0, (
            group
        )
        assert group.get("asset_current", 0) == (20000 if month == 3 else 0), group
        assert group.get("liability_current", 0) == 0, group
        assert group["asset_cash"] == 180000 * month - (20000 if month == 3 else 0), group
    env.cr.commit()
    print("Demo loaded: January to March 2026")
