DB      ?= kpiten
MODULES ?= kpiten,kpiten_override,kpiten_demo

# mot de passe Postgres de l'utilisateur odoo : PGPASSWORD dans .env (voir
# .env.example), ni dans odoo.conf ni dans le dépôt ; lu par libpq pour odoo-bin,
# createdb, etc. Surcharge : make run PGPASSWORD=xxx
-include .env
export PGPASSWORD

PY      := .venv/bin/python
ODOO    := $(PY) src/odoo/odoo-bin -c odoo.conf
# la sous-commande shell doit venir AVANT les options d'odoo-bin
ODOO_SHELL := $(PY) src/odoo/odoo-bin shell -c odoo.conf

N       ?= 100000
# filtre des bases visibles en mode multi-bases (regex) ; vide = celui de odoo.conf
DBFILTER ?=

.PHONY: repos venv apps db run run-db shell update add-sales sync

## Clone / met à jour les sources (git-aggregator)
repos:
	gitaggregate -c repos.yml -j 4

## Venv Odoo (Python 3.12) : dépendances d'Odoo + addons
venv:
	uv venv --allow-existing --python 3.12 .venv
	uv pip install --python $(PY) -r src/odoo/requirements.txt
	@for r in src/oca-server-tools src/kpiten-addons src/kpiten-override; do \
	  [ -f $$r/requirements.txt ] && uv pip install --python $(PY) -r $$r/requirements.txt || true; \
	done
	# le module Odoo kpiten importe kpiten_core
	uv pip install --python $(PY) -e src/kpiten-core

## Environnements des applications (un uv.lock par projet)
apps:
	@for a in kpiten-core nicegui-kpiten shiny-kpiten; do (cd src/$$a && uv sync); done

## Crée la base DB et installe MODULES :  make db DB=kpiten
db:
	createdb -U odoo -h localhost $(DB)
	$(ODOO) -d $(DB) -i $(MODULES) --stop-after-init

## Met à jour MODULES sur DB
update:
	$(ODOO) -d $(DB) -u $(MODULES) --stop-after-init

## Ajoute N ventes de 4 lignes à la base DB (module kpiten_sale_stock_demo_big
## installé) :  make add-sales DB=big N=100000
add-sales:
	echo "env.ref('kpiten_sale_stock_demo_big.demo_generator_sale_big').add_big_sales($(N))" | $(ODOO_SHELL) -d $(DB)

## Odoo multi-bases : PAS de -d (qui restreint Odoo à une seule base). Les bases
## visibles sont celles de odoo.conf (dbfilter), ou de DBFILTER ; la base se
## choisit à la connexion.   make run  |  make run DBFILTER='^(big|dash)$$'
run:
	$(ODOO) $(if $(DBFILTER),--db-filter '$(DBFILTER)')

## Odoo sur une seule base :  make run-db DB=big
run-db:
	$(ODOO) -d $(DB)

shell:
	$(ODOO_SHELL) -d $(DB)

## Synchronise les parquets de DB depuis Postgres (process à part : à mettre en
## cron / timer systemd ; les dashboards ne font que lire).
##   make sync DB=big            incrémental
##   make sync DB=big FULL=1     reconstruit toutes les tables
sync:
	cd src/kpiten-core && .venv/bin/python -m kpiten_core.sync --db $(DB) $(if $(FULL),--full)
