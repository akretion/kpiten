DB      ?= kpiten
MODULES ?= kpiten,kpiten_data

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

.PHONY: check-repos repos venv apps db run run-db shell update add-sales sync up down restart status logs sample-fixtures

## Refuse d'agréger si des commits n'existent que localement dans src/ :
## git-aggregator remet la branche cible à l'état du remote (reset --hard) et les
## perdrait. Pousser d'abord, ou passer outre :  make repos FORCE=1
check-repos:
	@bad=0; for d in src/*/; do \
	  [ -e $$d.git ] || continue; \
	  n=$$(git -C $$d rev-list --branches --not --remotes --count 2>/dev/null); \
	  if [ "$${n:-0}" -gt 0 ]; then echo "$$d : $$n commit(s) non poussé(s)"; bad=1; fi; \
	done; \
	if [ $$bad = 1 ]; then \
	  echo "make repos les écraserait : git -C src/<dossier> push, ou make repos FORCE=1"; exit 1; \
	fi

## Clone / met à jour les sources (git-aggregator)
repos: $(if $(FORCE),,check-repos)
	gitaggregate -c repos.yml -j 4

## Venv Odoo (Python 3.12) : dépendances d'Odoo + addons
venv:
	uv venv --allow-existing --python 3.12 .venv
	uv pip install --python $(PY) -r src/odoo/requirements.txt
	@for r in src/oca-server-tools src/kpiten-addons; do \
	  [ -f $$r/requirements.txt ] && uv pip install --python $(PY) -r $$r/requirements.txt || true; \
	done
	# le module Odoo kpiten importe kpiten_core
	uv pip install --python $(PY) -e src/kpiten-core

## Environnements des applications (un uv.lock par projet)
apps:
	@for a in kpiten-core nicegui-kpiten shiny-kpiten marimo-kpiten; do (cd src/$$a && uv sync); done

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

## Les trois services (Odoo :8069, Shiny :5000, NiceGUI :5001), détachés du
## terminal, via scripts/kpiten-stack ; logs dans data/logs/.
##   make up | down | restart | status        tous
##   make restart SVC=shiny                    un seul : odoo | shiny | nicegui | marimo
##   make logs [SVC=shiny]                     suit les logs (Ctrl-C pour quitter)
SVC ?= all
up:
	scripts/kpiten-stack start $(SVC)

down:
	scripts/kpiten-stack stop $(SVC)

restart:
	scripts/kpiten-stack restart $(SVC)

status:
	scripts/kpiten-stack status $(SVC)

logs:
	tail -n 30 -F data/logs/$(if $(filter all,$(SVC)),*,$(SVC)).log

## Régénère les jeux d'essai réels des tests de kpiten-core (échantillons parquet des
## modèles des dashboards + leurs tuiles), depuis la base DB (parquet_sample installé).
sample-fixtures:
	$(ODOO_SHELL) -d $(DB) < src/kpiten-core/tests/data/make_fixtures.py

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
