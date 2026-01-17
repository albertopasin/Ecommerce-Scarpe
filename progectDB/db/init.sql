-- Drop tables if they already exist (with CASCADE to drop dependent constraints)
DROP TABLE IF EXISTS categoria CASCADE;
DROP TABLE IF EXISTS immagini CASCADE;
DROP TABLE IF EXISTS persona CASCADE;
DROP TABLE IF EXISTS carrello CASCADE;
DROP TABLE IF EXISTS prodotto CASCADE;
DROP TABLE IF EXISTS recensioni CASCADE;
DROP TABLE IF EXISTS taglie CASCADE;
DROP TABLE IF EXISTS prodottiincarrello CASCADE;
DROP TABLE IF EXISTS carte CASCADE;
DROP TABLE IF EXISTS ordini CASCADE;
DROP TABLE IF EXISTS dativenditori CASCADE;
DROP TABLE IF EXISTS indirizzo CASCADE;
DROP TABLE IF EXISTS prodottiinordine CASCADE;
DROP TABLE IF EXISTS messaggi CASCADE;
DROP TABLE IF EXISTS amministratori CASCADE;

create table amministratori
(
    amm_email    text,
    amm_password text,
    id           serial
        constraint amministratori_pk
            primary key
);

alter table amministratori
    owner to postgres;

create table immagini
(
    id       serial
        primary key,
    percorso text,
    formato  text
);

alter table immagini
    owner to postgres;

create table categoria
(
    nome        text not null,
    id          serial
        primary key,
    id_immagine integer
        references immagini
);

alter table categoria
    owner to postgres;

create table persona
(
    email       text not null
        primary key,
    password    text not null,
    ntelefono   text not null,
    soprannome  text not null,
    venditore   boolean,
    nome        text not null,
    cognome     text not null,
    datanascita date not null,
    codfiscale  text not null,
    immagine    integer
        references immagini
);

alter table persona
    owner to postgres;

create table carrello
(
    prezzotot double precision default 0,
    id        serial
        primary key,
    utente    text not null
        references persona
);

alter table carrello
    owner to postgres;

create table prodotto
(
    id          serial
        primary key,
    nome        text                       not null,
    prezzo      double precision default 0 not null,
    descrizione text,
    venditore   text                       not null
        references persona,
    categoria   integer                    not null
        references categoria,
    colore      text,
    id_immagine integer
        references immagini
);

alter table prodotto
    owner to postgres;

create table recensioni
(
    utente     text    not null
        references persona
            on update cascade on delete cascade,
    prodotto   integer not null
        references prodotto
            on update cascade on delete cascade,
    recensione text    not null,
    stelle     integer not null,
    id         serial
        constraint recensioni_pk
            primary key
);

alter table recensioni
    owner to postgres;

create table taglie
(
    taglia    integer not null,
    id_scarpa integer not null
        references prodotto,
    quantità  integer,
    primary key (taglia, id_scarpa)
);

alter table taglie
    owner to postgres;

create table prodottiincarrello
(
    prodotto integer not null,
    carrello integer not null
        references carrello,
    quantita integer not null,
    taglia   integer not null,
    constraint prodottiincarrello_pk
        primary key (prodotto, carrello, taglia),
    foreign key (taglia, prodotto) references taglie
);

alter table prodottiincarrello
    owner to postgres;

create table carte
(
    persona      text not null
        references persona,
    numero       text not null,
    datascadenza text not null,
    cvv          integer,
    nome         text not null,
    cognome      text not null,
    id           serial
        primary key
);

alter table carte
    owner to postgres;

create table ordini
(
    dataacquisto        date    not null,
    stato               text    not null,
    indirizzospedizione text    not null,
    pagato              boolean default false,
    dataprevista        date,
    id                  serial
        primary key,
    idcarrello          integer not null
        references carrello,
    idcarta             integer
        references carte
);

alter table ordini
    owner to postgres;

create table dativenditori
(
    persona text
        references persona,
    piva    text not null,
    azienda text,
    id      serial
);

alter table dativenditori
    owner to postgres;

create table indirizzo
(
    citta        text    not null,
    via          text    not null,
    numero       integer not null,
    cap          integer not null,
    provincia    text    not null,
    persona      text
        references persona,
    id           serial
        primary key,
    fatturazione boolean default false
);

alter table indirizzo
    owner to postgres;

create table prodottiinordine
(
    prodotto integer not null,
    ordine   integer not null
        constraint prodottiinordine_ordini__fk
            references ordini,
    quantita integer,
    taglia   integer not null,
    constraint prodottiinordine_pk
        primary key (prodotto, ordine, taglia),
    constraint prodottiinordine_taglie__fk
        foreign key (taglia,prodotto) references taglie 
);

alter table prodottiinordine
    owner to postgres;

create table messaggi
(
    id           serial
        primary key,
    destinatario text not null
        references persona,
    titolo       text not null,
    testo        text not null,
    data         timestamp default CURRENT_TIMESTAMP
);

alter table messaggi
    owner to postgres;

    