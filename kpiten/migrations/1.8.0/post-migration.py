# kt.config : `ai_send_values` (a boolean) becomes `ai_send_level`. A database that
# did not send the values keeps sending the columns only ; the others get the summary
# with pseudonyms (the new default).


def migrate(cr, version):
    cr.execute(
        "SELECT 1 FROM information_schema.columns"
        " WHERE table_name = 'kt_config' AND column_name = 'ai_send_values'"
    )
    if cr.fetchone():
        cr.execute(
            "UPDATE kt_config SET ai_send_level = 'schema' WHERE ai_send_values IS FALSE"
        )
