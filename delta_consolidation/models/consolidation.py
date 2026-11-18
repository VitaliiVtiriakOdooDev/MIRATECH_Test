import calendar
from collections import defaultdict
from datetime import date

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class AccountAccount(models.Model):
    _inherit = "account.account"

    delta_intercompany = fields.Boolean(
        string="Eliminate intercompany balances",
        help="Mark loan and other non-trade intercompany accounts. Trade receivable and payable accounts are included automatically.",
    )


class Consolidation(models.Model):
    _name = "delta.consolidation"
    _description = "Group consolidation snapshot"
    _order = "date_end desc, id desc"

    name = fields.Char(required=True)
    date_end = fields.Date(required=True, string="Month end")
    company_ids = fields.Many2many("res.company", required=True, string="Operating companies")
    elimination_company_id = fields.Many2one(
        "res.company", required=True, string="Elimination company"
    )
    journal_id = fields.Many2one("account.journal", required=True, string="Elimination journal")
    clearing_account_id = fields.Many2one(
        "account.account", required=True, string="Intercompany clearing account"
    )
    move_id = fields.Many2one("account.move", readonly=True, copy=False)
    source_move_ids = fields.Many2many(
        "account.move", string="Elimination source entries", readonly=True, copy=False
    )
    line_ids = fields.One2many("delta.consolidation.line", "consolidation_id", readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Generated")], default="draft", required=True, readonly=True
    )

    def action_generate(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("This snapshot has already been generated."))
        end = self.date_end
        if end.day != calendar.monthrange(end.year, end.month)[1]:
            raise UserError(_("Choose the last day of a month."))
        elim = self.elimination_company_id
        if (
            elim in self.company_ids
            or self.journal_id.company_id != elim
            or self.clearing_account_id.company_id != elim
        ):
            raise UserError(
                _(
                    "The elimination company must be separate, and the journal and clearing account must belong to it."
                )
            )
        if not set(self.company_ids.ids + [elim.id]).issubset(set(self.env.companies.ids)):
            raise UserError(_("Enable access to all selected companies before generating."))
        currency = elim.currency_id
        month_start = date(end.year, end.month, 1)
        lines = self.env["account.move.line"].search(
            [
                ("company_id", "in", self.company_ids.ids),
                ("parent_state", "=", "posted"),
                ("date", "<=", end),
                ("account_id.account_type", "not in", ["off_balance"]),
            ]
        )
        partners = self.company_ids.mapped("partner_id").commercial_partner_id
        totals = defaultdict(float)
        local_totals = defaultdict(float)
        eliminations = defaultdict(float)
        source_moves = self.env["account.move"]
        for line in lines:
            kind = line.account_id.account_type
            pnl = kind.startswith(("income", "expense"))
            if pnl and line.date < month_start:
                kind = "equity_unaffected"
            amount = line.company_currency_id._convert(line.balance, currency, line.company_id, end)
            totals[(line.company_id.id, kind)] += amount
            local_totals[(line.company_id.id, kind)] += line.balance
            is_trade = kind in ("asset_receivable", "liability_payable")
            is_intercompany = (
                line.partner_id.commercial_partner_id in partners
                and line.partner_id.commercial_partner_id
                != line.company_id.partner_id.commercial_partner_id
            )
            if is_intercompany and (pnl or is_trade or line.account_id.delta_intercompany):
                eliminations[kind] -= amount
                source_moves |= line.move_id
        # A separate account per type keeps the journal entry readable and the report classified.
        accounts = (
            self.env["account.account"]
            .with_company(elim)
            .search([("company_id", "=", elim.id), ("deprecated", "=", False)])
        )
        by_type = {
            account.account_type: account
            for account in accounts
            if account != self.clearing_account_id
        }
        missing = [
            kind
            for kind, value in eliminations.items()
            if not currency.is_zero(value) and kind not in by_type
        ]
        if missing:
            raise UserError(
                _("Create elimination-company accounts for these account types: %s")
                % ", ".join(sorted(missing))
            )
        eliminations = {kind: currency.round(value) for kind, value in eliminations.items()}
        commands = []
        for kind, value in sorted(eliminations.items()):
            value = currency.round(value)
            if not currency.is_zero(value):
                commands.append(
                    Command.create(
                        {
                            "name": _("Eliminate %s") % kind,
                            "account_id": by_type[kind].id,
                            "debit": max(value, 0),
                            "credit": max(-value, 0),
                        }
                    )
                )
        difference = currency.round(sum(eliminations.values()))
        if not currency.is_zero(difference):
            commands.append(
                Command.create(
                    {
                        "name": _("Timing and translation clearing"),
                        "account_id": self.clearing_account_id.id,
                        "debit": max(-difference, 0),
                        "credit": max(difference, 0),
                    }
                )
            )
        move = self.env["account.move"]
        if commands:
            move = move.with_company(elim).create(
                {
                    "move_type": "entry",
                    "company_id": elim.id,
                    "journal_id": self.journal_id.id,
                    "date": end,
                    "ref": self.name,
                    "line_ids": commands,
                }
            )
            move.action_post()
        report = []
        for (company_id, kind), amount in sorted(totals.items()):
            report.append(
                Command.create(
                    {
                        "company_id": company_id,
                        "account_type": kind,
                        "amount": currency.round(amount),
                        "local_amount": local_totals[(company_id, kind)],
                    }
                )
            )
        for company in self.company_ids:
            current_usd = sum(
                amount
                for (company_id, kind), amount in totals.items()
                if company_id == company.id and kind.startswith(("income", "expense"))
            )
            current_local = sum(
                amount
                for (company_id, kind), amount in local_totals.items()
                if company_id == company.id and kind.startswith(("income", "expense"))
            )
            report.append(
                Command.create(
                    {
                        "company_id": company.id,
                        "account_type": "equity_current_result",
                        "amount": currency.round(current_usd),
                        "local_amount": current_local,
                    }
                )
            )
        group = defaultdict(float)
        for (company_id, kind), amount in totals.items():
            group[kind] += amount
        for kind, amount in eliminations.items():
            group[kind] += amount
        if not currency.is_zero(difference):
            group[self.clearing_account_id.account_type] -= difference
        for kind, amount in sorted(group.items()):
            report.append(Command.create({"account_type": kind, "amount": currency.round(amount)}))
        current_result = sum(
            amount for kind, amount in group.items() if kind.startswith(("income", "expense"))
        )
        report.append(
            Command.create(
                {"account_type": "equity_current_result", "amount": currency.round(current_result)}
            )
        )
        self.write(
            {
                "move_id": move.id if move else False,
                "line_ids": report,
                "source_move_ids": [Command.set(source_moves.ids)],
            }
        )
        self.write({"state": "done"})
        return True

    def write(self, vals):
        if any(record.state == "done" for record in self):
            raise UserError(_("Generated snapshots cannot be modified."))
        return super().write(vals)

    def unlink(self):
        if any(record.state == "done" for record in self):
            raise UserError(
                _(
                    "Generated snapshots cannot be deleted. Reverse their journal entry through Accounting if needed."
                )
            )
        return super().unlink()


class ConsolidationLine(models.Model):
    _name = "delta.consolidation.line"
    _description = "Consolidation result"
    _order = "company_id, account_type"

    @api.model_create_multi
    def create(self, vals_list):
        runs = self.env["delta.consolidation"].browse(
            [vals.get("consolidation_id") for vals in vals_list if vals.get("consolidation_id")]
        )
        if any(run.state != "draft" for run in runs):
            raise UserError(_("Generated snapshots cannot be modified."))
        return super().create(vals_list)

    consolidation_id = fields.Many2one("delta.consolidation", required=True, ondelete="cascade")
    company_id = fields.Many2one(
        "res.company", string="Company", help="Empty means consolidated group."
    )
    currency_id = fields.Many2one(related="consolidation_id.elimination_company_id.currency_id")
    local_currency_id = fields.Many2one(
        related="company_id.currency_id", string="Local currency code"
    )
    local_amount = fields.Monetary(currency_field="local_currency_id", string="Local currency")
    account_type = fields.Char(required=True, string="Account type")
    amount = fields.Monetary(string="Debit less credit (group currency)")
