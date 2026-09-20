-- `odoo neutralize` : the address of the Marimo front for a docker (docky) stack, see
-- https://github.com/akretion/docky-odoo-template-shared (branch kpiten, kpiten.dc.yml).
--   internal_url : Odoo asks the front for a session on the docker network, service kpiten-marimo
--   external_url : the browser goes through traefik, http://<project>-marimo.localhost : the base
--                  url is http://<project>.localhost, `-marimo` goes after the first label of its host
UPDATE ir_config_parameter AS front
   SET value = jsonb_build_object(
           'application', 'Marimo',
           'internal_url', 'http://kpiten-marimo:5002',
           'external_url', regexp_replace(base.value, '^(https?://)([^./:]+)', '\1\2-marimo')
       )::text
  FROM ir_config_parameter AS base
 WHERE front.key = 'kpiten_marimo_service'
   AND base.key = 'web.base.url';
