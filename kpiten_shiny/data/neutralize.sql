-- `odoo neutralize` : the address of the Shiny front for a docker (docky) stack, see
-- https://github.com/akretion/docky-odoo-template-shared (branch kpiten, kpiten.dc.yml).
--   internal_url : Odoo asks the front for a session on the docker network, service kpiten-shiny
--   external_url : the browser goes through traefik, http://<project>-shiny.localhost : the base
--                  url is http://<project>.localhost, `-shiny` goes after the first label of its host
UPDATE ir_config_parameter AS front
   SET value = jsonb_build_object(
           'application', 'Shiny',
           'internal_url', 'http://kpiten-shiny:5000',
           'external_url', regexp_replace(base.value, '^(https?://)([^./:]+)', '\1\2-shiny')
       )::text
  FROM ir_config_parameter AS base
 WHERE front.key = 'kpiten_shiny_service'
   AND base.key = 'web.base.url';
