-- Rimuovere i trigger esistenti
DROP TRIGGER IF EXISTS trigger_check_email_format ON persona;
DROP TRIGGER IF EXISTS trigger_check_telefono_format ON persona;
DROP TRIGGER IF EXISTS trigger_check_recensione_prodotto ON recensioni;
DROP TRIGGER IF EXISTS trigger_aggiorna_totale_carrello ON prodottiincarrello;
DROP TRIGGER IF EXISTS trigger_verifica_quantita_disponibile ON prodottiincarrello;
DROP TRIGGER IF EXISTS trigger_check_indirizzo_fatturazione ON indirizzo;
DROP TRIGGER IF EXISTS trigger_elimina_ordini ON prodotto;

-- Rimuovere i vincoli CHECK esistenti
ALTER TABLE persona DROP CONSTRAINT IF EXISTS codicefiscale_valid;
ALTER TABLE taglie DROP CONSTRAINT IF EXISTS quantità_positive;
ALTER TABLE indirizzo DROP CONSTRAINT IF EXISTS cap_valid;
ALTER TABLE recensioni DROP CONSTRAINT IF EXISTS stelle_range;
ALTER TABLE prodotto DROP CONSTRAINT IF EXISTS prezzo_positive;
ALTER TABLE ordini DROP CONSTRAINT IF EXISTS data_prevista;
ALTER TABLE carte DROP CONSTRAINT IF EXISTS cvv_valid;
ALTER TABLE prodottiinordine DROP CONSTRAINT IF EXISTS quantità_non_negativa;

-- Aggiunta di un vincolo di controllo per il campo codicefiscale
ALTER TABLE persona
ADD CONSTRAINT codicefiscale_valid CHECK (codfiscale ~* '^[A-Z0-9]{16}$');

-- Vincolo CHECK per assicurarsi che la 'quantità' in 'taglie' non sia negativa
ALTER TABLE taglie
ADD CONSTRAINT quantità_positive CHECK (quantità >= 0);

-- Vincolo CHECK per il 'cap' in 'indirizzo' per garantire che sia nel formato valido
ALTER TABLE indirizzo
ADD CONSTRAINT cap_valid CHECK (cap >= 10000 AND cap <= 99999);

-- Vincolo CHECK per le 'stelle' in 'recensioni' per garantire che il rating sia tra 1 e 5
ALTER TABLE recensioni
ADD CONSTRAINT stelle_range CHECK (stelle >= 1 AND stelle <= 5);

-- Vincolo CHECK per 'prezzo' in 'prodotto' per garantire che sia positivo
ALTER TABLE prodotto
ADD CONSTRAINT prezzo_positive CHECK (prezzo >= 0);

-- Vincolo CHECK per 'dataprevista' in 'ordini' per garantire che sia dopo 'dataacquisto'
ALTER TABLE ordini
ADD CONSTRAINT data_prevista CHECK (dataprevista > dataacquisto);

-- Vincolo CHECK per 'cvv' in 'carte' per assicurarsi che sia un numero valido di 3 cifre
ALTER TABLE carte
ADD CONSTRAINT cvv_valid CHECK (cvv >= 100 AND cvv <= 999);

-- Vincolo CHECK per 'quantita' in 'prodottiinordine' per garantirne il valore non negativo
ALTER TABLE prodottiinordine
ADD CONSTRAINT quantità_non_negativa CHECK (quantita >= 0);

-- Trigger per assicurarsi che il formato della email in 'persona' sia valido
CREATE OR REPLACE FUNCTION check_email_format()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.email !~* '^[^@]+@[^@]+\.[^@]+$' THEN
        RAISE EXCEPTION 'Formato email non valido';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_check_email_format
BEFORE INSERT OR UPDATE ON persona
FOR EACH ROW
EXECUTE FUNCTION check_email_format();

-- Trigger per assicurarsi che il numero di telefono in 'persona' sia valido
CREATE OR REPLACE FUNCTION check_telefono_format()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.ntelefono !~ '^[0-9]{10}$' THEN
        RAISE EXCEPTION 'Numero di telefono non valido. Deve contenere 10 cifre';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_check_telefono_format
BEFORE INSERT OR UPDATE ON persona
FOR EACH ROW
EXECUTE FUNCTION check_telefono_format();

-- Trigger per prevenire che un utente aggiunga recensioni sui propri prodotti
CREATE OR REPLACE FUNCTION check_recensione_prodotto()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM prodotto
        WHERE prodotto.id = NEW.prodotto AND prodotto.venditore = NEW.utente
    ) THEN
        RAISE EXCEPTION 'Un utente non può recensire il proprio prodotto';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_check_recensione_prodotto
BEFORE INSERT ON recensioni
FOR EACH ROW
EXECUTE FUNCTION check_recensione_prodotto();

-- Trigger per aggiornare 'prezzotot' in 'carrello' basato su 'prodottiincarrello'
CREATE OR REPLACE FUNCTION aggiorna_totale_carrello()
RETURNS trigger AS
$$
BEGIN
    UPDATE carrello
    SET prezzotot = (
        SELECT SUM(p.prezzo * pci.quantita)
        FROM prodottiincarrello pci
        JOIN prodotto p ON pci.prodotto = p.id
        WHERE pci.carrello = NEW.carrello
    )
    WHERE id = NEW.carrello;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_aggiorna_totale_carrello
AFTER INSERT OR UPDATE ON prodottiincarrello
FOR EACH ROW
EXECUTE FUNCTION aggiorna_totale_carrello();

-- Trigger per verificare la quantità disponibile prima dell'inserimento in 'prodottiincarrello'
CREATE OR REPLACE FUNCTION verifica_quantita_disponibile()
RETURNS trigger AS
$$
BEGIN
    IF NEW.quantita > (SELECT quantità FROM taglie WHERE id_scarpa = NEW.prodotto AND taglia = NEW.taglia) THEN
        RAISE EXCEPTION 'Quantità richiesta maggiore di quella disponibile per questa taglia';
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_verifica_quantita_disponibile
BEFORE INSERT ON prodottiincarrello
FOR EACH ROW
EXECUTE FUNCTION verifica_quantita_disponibile();


--Quando elimini un utente (persona), verranno eliminate automaticamente tutte le entità collegate a lui
CREATE OR REPLACE FUNCTION cascade_delete_persona() RETURNS TRIGGER AS $$
BEGIN
    -- Elimina il carrello e tutto il suo contenuto
    DELETE FROM prodottiincarrello WHERE carrello IN (SELECT id FROM carrello WHERE utente = OLD.email);
    DELETE FROM carrello WHERE utente = OLD.email;

    -- Elimina carte di credito associate
    DELETE FROM carte WHERE persona = OLD.email;

    -- Elimina indirizzi associati
    DELETE FROM indirizzo WHERE persona = OLD.email;

    -- Elimina messaggi ricevuti
    DELETE FROM messaggi WHERE destinatario = OLD.email;

    -- Elimina ordini dell'utente
    DELETE FROM prodottiinordine WHERE ordine IN (SELECT id FROM ordini WHERE idcarrello IN (SELECT id FROM carrello WHERE utente = OLD.email));
    DELETE FROM ordini WHERE idcarrello IN (SELECT id FROM carrello WHERE utente = OLD.email);

    -- Elimina recensioni scritte dall'utente
    DELETE FROM recensioni WHERE utente = OLD.email;

    -- Elimina dati venditore e prodotti venduti dall'utente
    DELETE FROM dativenditori WHERE persona = OLD.email;
    DELETE FROM prodottiinordine WHERE prodotto IN (SELECT id FROM prodotto WHERE venditore = OLD.email);
    DELETE FROM taglie WHERE id_scarpa IN (SELECT id FROM prodotto WHERE venditore = OLD.email);
    DELETE FROM recensioni WHERE prodotto IN (SELECT id FROM prodotto WHERE venditore = OLD.email);
    DELETE FROM prodotto WHERE venditore = OLD.email;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER delete_persona_cascade
BEFORE DELETE ON persona
FOR EACH ROW
EXECUTE FUNCTION cascade_delete_persona();



--Quando elimini un prodotto, verranno eliminate tutte le entità collegate
CREATE OR REPLACE FUNCTION cascade_delete_prodotto() RETURNS TRIGGER AS $$
BEGIN
    -- Elimina recensioni associate al prodotto
    DELETE FROM recensioni WHERE prodotto = OLD.id;

    -- Elimina taglie associate
    DELETE FROM taglie WHERE id_scarpa = OLD.id;

    -- Elimina prodotti nei carrelli
    DELETE FROM prodottiincarrello WHERE prodotto = OLD.id;

    -- Elimina prodotti negli ordini
    DELETE FROM prodottiinordine WHERE prodotto = OLD.id;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER delete_prodotto_cascade
BEFORE DELETE ON prodotto
FOR EACH ROW
EXECUTE FUNCTION cascade_delete_prodotto();




--Quando elimini un ordine, verranno eliminate tutte le entità collegate
CREATE OR REPLACE FUNCTION cascade_delete_ordine() RETURNS TRIGGER AS $$
BEGIN
    -- Elimina i prodotti nell'ordine
    DELETE FROM prodottiinordine WHERE ordine = OLD.id;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER delete_ordine_cascade
BEFORE DELETE ON ordini
FOR EACH ROW
EXECUTE FUNCTION cascade_delete_ordine();
