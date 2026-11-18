from odoo import Command
from odoo.tests.common import TransactionCase


class TestConsolidation(TransactionCase):
    def test_eliminates_matched_trade_and_preserves_books(self):
        company = self.env["res.company"].create(
            {"name": "Test parent", "currency_id": self.env.company.currency_id.id}
        )
        other = self.env["res.company"].create(
            {"name": "Other group", "currency_id": company.currency_id.id}
        )
        elim = self.env["res.company"].create(
            {"name": "Eliminations", "currency_id": company.currency_id.id}
        )
        self.env.user.company_ids |= company | other | elim

        def account(c, code, kind):
            return (
                self.env["account.account"]
                .with_company(c)
                .create(
                    {
                        "name": code,
                        "code": code,
                        "account_type": kind,
                        "company_id": c.id,
                        "reconcile": kind in ("asset_receivable", "liability_payable"),
                    }
                )
            )

        revenue = account(company, "D901", "income")
        receivable = account(company, "D101", "asset_receivable")
        expense = account(other, "D601", "expense")
        payable = account(other, "D201", "liability_payable")
        for code, kind in [
            ("E901", "income"),
            ("E101", "asset_receivable"),
            ("E601", "expense"),
            ("E201", "liability_payable"),
        ]:
            account(elim, code, kind)
        clearing = account(elim, "E102", "asset_current")

        def journal(c):
            return (
                self.env["account.journal"]
                .with_company(c)
                .create({"name": "Delta test", "code": "DT", "type": "general", "company_id": c.id})
            )

        j1, j2, je = journal(company), journal(other), journal(elim)

        def entry(c, j, partner, a, b):
            m = (
                self.env["account.move"]
                .with_company(c)
                .create(
                    {
                        "journal_id": j.id,
                        "date": "2026-03-31",
                        "line_ids": [
                            Command.create(
                                {
                                    "name": "test",
                                    "account_id": a.id,
                                    "partner_id": partner.id,
                                    "debit": 100,
                                }
                            ),
                            Command.create(
                                {
                                    "name": "test",
                                    "account_id": b.id,
                                    "partner_id": partner.id,
                                    "credit": 100,
                                }
                            ),
                        ],
                    }
                )
            )
            m.action_post()

        entry(company, j1, other.partner_id, receivable, revenue)
        entry(other, j2, company.partner_id, expense, payable)
        run = self.env["delta.consolidation"].create(
            {
                "name": "March",
                "date_end": "2026-03-31",
                "company_ids": [Command.set((company | other).ids)],
                "elimination_company_id": elim.id,
                "journal_id": je.id,
                "clearing_account_id": clearing.id,
            }
        )
        run.action_generate()
        group = run.line_ids.filtered(lambda line: not line.company_id)
        self.assertTrue(all(company.currency_id.is_zero(line.amount) for line in group))
        self.assertEqual(run.move_id.state, "posted")
        self.assertEqual(sum(run.move_id.line_ids.mapped("balance")), 0)
        self.assertEqual(
            sum(
                run.line_ids.filtered(
                    lambda line: line.company_id == company and line.account_type == "income"
                ).mapped("amount")
            ),
            -100,
        )
