Diciamo a Django di segnare la migrazione come "non applicata" senza però tentare di cancellare le tabelle (che sono già in uno stato errato).

docker compose exec django-web uv run manage.py migrate webApp zero --fake

2. Cancella le Tabelle "corrotte"

Ora dobbiamo cancellare manualmente le tabelle che esistono ma sono sbagliate.
Bash

docker compose exec mysql mysql -u dbuser -p my_db
(Inserire password Cammell0 del db)

Una volta dentro il prompt mysql, esegui questi comandi per cancellare le tabelle della tua app (l'ordine è importante a causa delle ForeignKey):

DROP TABLE IF EXISTS webApp_author_papers;
DROP TABLE IF EXISTS webApp_pdfpaper;
DROP TABLE IF EXISTS webApp_dataset_papers;
DROP TABLE IF EXISTS webApp_dataset;
DROP TABLE IF EXISTS webApp_paper;
DROP TABLE IF EXISTS webApp_author;
DROP TABLE IF EXISTS webApp_conference;
DROP TABLE IF EXISTS webApp_operations;
exit;

3. Riapplica le Migrazioni (per davvero)

docker compose exec django-web uv run manage.py migrate webApp

1. SHOW TABLES;
2. DESCRIBE <nome_tabella>

ALTER TABLE annotator_annotation MODIFY COLUMN embedding BLOB;
