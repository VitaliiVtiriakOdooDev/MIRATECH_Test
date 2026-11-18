from odoo import fields, models


class AccountAccount(models.Model):
    _inherit = "account.account"

    delta_intercompany = fields.Boolean(
        string="Eliminate intercompany balances",
        help="Mark loan and other non-trade intercompany accounts. Trade receivable and payable accounts are included automatically.",
    )
