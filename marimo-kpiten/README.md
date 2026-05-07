# Kpiten

## Setup
> Kpiten a besoin d'avoir odoo déjà lancé pour tourner. **Plante dans le cas échéant** (temporaire)

### Variables d'environnement
Actuellement, les variables :
- `ODOO_SERVER_HOST`
- `ODOO_SERVER_PORT`
- `POSTGRES_URL`
sont **requises** et doivent être définies dans le fichier `.env`. `.env.example` donne des explications sur ce qu'elles devraient être.

### Dans Odoo
Il faut créer un profil qui contient la table Sale Order. Le nom n'a normalement pas d'importance, mais l'application a été testée avec un profil appelé **Sales** et une seule table à l'intérieur (sale.order).

### Lancer l'application
```bash
$ . .venv/bin/activate
(marimo-kpiten) $ uv add -r requirements.txt
(marimo-kpiten) $ uv run main.py # tout le temps cette commande pour lancer le serveur
# uvicorn devrait tourner
```

## Usage normal
> Avec navigateur
1. Visiter http://localhost:5000/
> Cela écrit la table Sales Order dans le dossier generated.
> La chose que l'ont doit voir à la visite de la page est
> Un écran qui indique une redirection vers /notebook.
2. Visister http://localhost:5000/notebook
> C'est là que le notebook Marimo est servit.
3. Faire des transformations sur la table Sales Order
4. Choisir l'onglet Python et copier tout le code de la transformation
5. Coller le code dans la zone de texte "Python Code"
6. Appuyer sur **Save to Kpiten**
> Vérifier Kpiten>Sales / le nom du profil créé plus tôt
> La transformation est stockée ici
7. Actualiser la page
> Une nouvelle table avec les transformations effectuée devrait être affichée en plus de Sales Order.