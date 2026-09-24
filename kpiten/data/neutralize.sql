-- `odoo neutralize` : the addresses of the fronts for a docker (docky) stack, see
-- https://github.com/akretion/docky-odoo-template-shared (branch kpiten, kpiten.dc.yml).

-- Shiny :
UPDATE ir_config_parameter AS front
   SET value = jsonb_build_object(
           'application', 'Shiny',
           'internal_url', 'http://kpiten-shiny:5000',
           'external_url', regexp_replace(base.value, '^(https?://)([^./:]+)', '\1\2-shiny')
       )::text
  FROM ir_config_parameter AS base
 WHERE front.key = 'kpiten_shiny_service'
   AND base.key = 'web.base.url';

-- NiceGUI :
UPDATE ir_config_parameter AS front
   SET value = jsonb_build_object(
           'application', 'NiceGUI',
           'internal_url', 'http://kpiten-nicegui:5001',
           'external_url', regexp_replace(base.value, '^(https?://)([^./:]+)', '\1\2-nicegui')
       )::text
  FROM ir_config_parameter AS base
 WHERE front.key = 'kpiten_nicegui_service'
   AND base.key = 'web.base.url';

-- Marimo :
UPDATE ir_config_parameter AS front
   SET value = jsonb_build_object(
           'application', 'Marimo',
           'internal_url', 'http://kpiten-marimo:5002',
           'external_url', regexp_replace(base.value, '^(https?://)([^./:]+)', '\1\2-marimo')
       )::text
  FROM ir_config_parameter AS base
 WHERE front.key = 'kpiten_marimo_service'
   AND base.key = 'web.base.url';
