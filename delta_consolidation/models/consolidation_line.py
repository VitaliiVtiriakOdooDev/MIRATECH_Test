from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ConsolidationLine(models.Model):
    _name = "delta.consolidation.line"
    _description = "Consolidation result"
    _order = "company_id, account_type"

    consolidation_id = fields.Many2one("delta.consolidation", required=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", help="Empty means consolidated group.")
    currency_id = fields.Many2one(related="consolidation_id.elimination_company_id.currency_id")
    local_currency_id = fields.Many2one(
        related="company_id.currency_id", string="Local currency code"
    )
    local_amount = fields.Monetary(currency_field="local_currency_id", string="Local currency")
    account_type = fields.Char(required=True, string="Account type")
    amount = fields.Monetary(string="Debit less credit (group currency)")

    @api.model_create_multi
    def create(self, vals_list):
        runs = self.env["delta.consolidation"].browse(
            [vals.get("consolidation_id") for vals in vals_list if vals.get("consolidation_id")]
        )
        if any(run.state != "draft" for run in runs):
            raise UserError(_("Generated snapshots cannot be modified."))
        return super().create(vals_list)
