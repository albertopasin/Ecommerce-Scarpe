from flask import Flask, request, render_template, redirect, url_for, flash, session
from sqlalchemy import create_engine, text
from config import Config  # Importa la classe Config
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
import os
from werkzeug.utils import secure_filename
import re
from sqlalchemy.sql import text

# Configurazione dell'app Flask
app = Flask(__name__)
app.secret_key = os.urandom(24) 
app.config.from_object(Config)  # Carica la configurazione dalla classe Config
engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])  # Usa la URI dal config

app.permanent_session_lifetime = timedelta(minutes=30)  # La durata della sessione è di 30 minuti
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",  # Consenti il reindirizzamento senza perdere i cookie
    SESSION_COOKIE_SECURE=False,    # False per HTTP, True per HTTPS (assicurati che sia appropriato)
    SESSION_COOKIE_HTTPONLY=True    # Protezione da accesso JavaScript
)

# Rotta per la pagina principale
@app.route('/')
def index():
    # Verifica se l'utente è loggato
    email = session.get('email')
    if email:
        # Mostra la home per l'utente loggato
        with engine.connect() as connection:
            result = connection.execute(text('SELECT * FROM prodotto'))
            resultc = connection.execute(text('SELECT categoria.id, categoria.nome, immagini.percorso AS immagine FROM categoria LEFT JOIN immagini ON categoria.id_immagine = immagini.id;'))
            prodotti = result.fetchall()
            categorie = resultc.fetchall()
        return render_template('index.html', prodotti=prodotti, categorie=categorie, email=email)
    
    # Se non è loggato, cancella la sessione e mostra la home base
    session.clear()
    with engine.connect() as connection:
        result = connection.execute(text('SELECT * FROM prodotto'))
        resultc = connection.execute(text('SELECT categoria.id, categoria.nome, immagini.percorso AS immagine FROM categoria LEFT JOIN immagini ON categoria.id_immagine = immagini.id;'))
        prodotti = result.fetchall()
        categorie = resultc.fetchall()
    return render_template('index.html', prodotti=prodotti, categorie=categorie)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error_message = None  # Variabile per memorizzare messaggi di errore

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        try:
            with engine.connect() as connection:
                # Primo controllo: tabella persona
                result = connection.execute(
                    text('SELECT password, soprannome, venditore FROM persona WHERE email = :email'),
                    {'email': email}
                ).fetchone()

                if result:
                    password_db = result[0]
                    soprannome_db = result[1]
                    venditore_db = result[2]

                    # Verifica la password hashata per persona
                    if check_password_hash(password_db, password):
                        # Login come utente normale o venditore
                        session['email'] = email
                        session['soprannome'] = soprannome_db
                        session['venditore'] = venditore_db
                        return redirect(url_for('index'))
                    else:
                        # Password errata per persona, nessun altro tentativo su persona
                        # Ora prova con amministratori
                        admin_result = connection.execute(
                            text('SELECT amm_password FROM amministratori WHERE amm_email = :email'),
                            {'email': email}
                        ).fetchone()

                        if admin_result:
                            admin_password_db = admin_result[0]
                            if check_password_hash(admin_password_db, password):
                                # Login come admin
                                session['email'] = email
                                session['soprannome'] = 'Admin'  # Puoi gestire il nome admin diversamente
                                session['venditore'] = True      # O un flag admin diverso
                                return redirect(url_for('admin_page'))
                            else:
                                error_message = 'Password errata per amministratore. Riprova.'
                        else:
                            error_message = 'Password errata. Riprova.'
                else:
                    # Nessun utente trovato in persona, controlla amministratori
                    admin_result = connection.execute(
                        text('SELECT amm_password FROM amministratori WHERE amm_email = :email'),
                        {'email': email}
                    ).fetchone()

                    if admin_result:
                        admin_password_db = admin_result[0]
                        if check_password_hash(admin_password_db, password):
                            # Login come admin
                            session['email'] = email
                            session['soprannome'] = 'Admin'
                            session['venditore'] = True
                            return redirect(url_for('admin_page'))
                        else:
                            error_message = 'Password errata per amministratore. Riprova.'
                    else:
                        # Non trovato neanche in amministratori
                        error_message = 'Email non registrata né come utente né come amministratore. Riprova.'
        
        except Exception as e:
            error_message = f'Errore durante il login: {str(e)}'

    return render_template('login.html', error_message=error_message)


@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    email = session.get('email')
    if not email:
        flash('Devi effettuare il login per aggiungere prodotti al carrello.', 'danger')
        return redirect(url_for('login'))

    product_id = request.form.get('product_id')
    taglia = request.form.get('taglia_selezionata')
    quantita = int(request.form.get('quantità', 1))

    if not taglia:
        flash('Devi selezionare una taglia.', 'danger')
        return redirect(url_for('product_details', product_id=product_id))

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            
            # Recupera la quantità disponibile per la taglia selezionata
            quantitaMax = connection.execute(
                text('SELECT quantità FROM taglie WHERE taglia = :taglia AND id_scarpa = :product_id'),
                {'taglia': taglia, 'product_id': product_id}
            ).fetchone()

            if quantitaMax is None:
                quantitaMax = 0
            else:
                quantitaMax = quantitaMax[0]

            if quantita > quantitaMax:
                flash(f'La quantità selezionata ({quantita}) supera quella disponibile ({quantitaMax}).', 'danger')
                return redirect(url_for('product_details', product_id=product_id))

            # Recupera il carrello dell'utente
            carrello = connection.execute(
                text('SELECT id FROM carrello WHERE utente = :utente'),
                {'utente': email}
            ).fetchone()

            if not carrello:
                flash('Errore: Carrello non trovato.', 'danger')
                return redirect(url_for('product_details', product_id=product_id))

            carrello_id = carrello[0]

            # Verifica se l'articolo con la stessa taglia esiste già nel carrello
            articolo_esistente = connection.execute(
                text(''' 
                    SELECT quantita 
                    FROM prodottiincarrello 
                    WHERE carrello = :carrello_id 
                    AND prodotto = :product_id 
                    AND taglia = :taglia
                '''), 
                {'carrello_id': carrello_id, 'product_id': product_id, 'taglia': taglia}
            ).fetchone()

            if articolo_esistente:
                # Aggiorna la quantità dell'articolo esistente (se taglia è la stessa)
                nuova_quantita = articolo_esistente[0] + quantita
                connection.execute(
                    text(''' 
                        UPDATE prodottiincarrello 
                        SET quantita = :nuova_quantita 
                        WHERE carrello = :carrello_id 
                        AND prodotto = :product_id 
                        AND taglia = :taglia
                    '''),
                    {'nuova_quantita': nuova_quantita, 'carrello_id': carrello_id, 'product_id': product_id, 'taglia': taglia}
                )
            else:
                # Aggiungi un nuovo articolo con la nuova taglia al carrello
                connection.execute(
                    text(''' 
                        INSERT INTO prodottiincarrello (carrello, prodotto, taglia, quantita) 
                        VALUES (:carrello_id, :product_id, :taglia, :quantita)
                    '''), 
                    {'carrello_id': carrello_id, 'product_id': product_id, 'taglia': taglia, 'quantita': quantita}
                )

            # Aggiorna il totale del carrello
            connection.execute(
                text(''' 
                    UPDATE carrello 
                    SET prezzotot = (
                        SELECT SUM(p.prezzo * pci.quantita) 
                        FROM prodottiincarrello pci 
                        JOIN prodotto p ON pci.prodotto = p.id 
                        WHERE pci.carrello = :carrello_id
                    ) 
                    WHERE id = :carrello_id
                '''), 
                {'carrello_id': carrello_id}
            )

            transaction.commit()
            
            # Aggiungi un messaggio diverso a seconda dello stato di login
            if email:
                flash('Prodotto aggiunto al carrello!', 'success')
            else:
                flash('Devi effettuare il login per aggiungere il prodotto al carrello.', 'danger')

    except Exception as e:
        if 'transaction' in locals():
            transaction.rollback()
        flash(f'Errore durante l\'aggiunta al carrello: {e}', 'danger')

    return redirect(url_for('product_details', product_id=product_id))


@app.route('/cart', methods=['GET'])
def cart():
    email = session.get('email')
    if not email:
        flash('Devi effettuare il login per vedere il carrello.', 'danger')
        return redirect(url_for('login'))

    with engine.connect() as connection:
        carrello = connection.execute(
            text('SELECT id FROM carrello WHERE utente = :utente'),
            {'utente': email}
        ).fetchone()

        if not carrello:
            flash('Errore: Carrello non trovato.', 'danger')
            return redirect(url_for('products'))

        carrello_id = carrello[0]

        cart_items = connection.execute(
            text('''
                SELECT pci.prodotto AS id_scarpa, p.nome, p.prezzo, pci.quantita, pci.taglia, i.percorso AS image_url
                FROM prodottiincarrello pci
                JOIN prodotto p ON pci.prodotto = p.id
                LEFT JOIN immagini i ON p.id_immagine = i.id
                WHERE pci.carrello = :carrello_id
            '''),
            {'carrello_id': carrello_id}
        ).fetchall()

        total_price = 0
        for item in cart_items:
            total_price += item.prezzo * item.quantita  

    return render_template('cart.html', cart=cart_items, total=total_price)

@app.route('/update_cart/<int:product_id>/<int:taglia_id>', methods=['POST'])
def update_cart(product_id, taglia_id):
    email = session.get('email')
    if not email:
        flash('Devi effettuare il login per aggiornare il carrello.', 'danger')
        return redirect(url_for('login'))

    nuova_quantita = int(request.form.get('quantita', 1))

    with engine.connect() as connection:
        try:
            transaction = connection.begin()
            connection.execute(
                text('''
                    UPDATE prodottiincarrello
                    SET quantita = :nuova_quantita
                    WHERE carrello = (SELECT id FROM carrello WHERE utente = :utente)
                    AND prodotto = :product_id AND taglia = :taglia_id
                '''),
                {'nuova_quantita': nuova_quantita, 'utente': email, 'product_id': product_id, 'taglia_id': taglia_id}
            )
            transaction.commit()
            flash('Carrello aggiornato con successo!', 'success')
        except Exception as e:
            transaction.rollback()
            flash(f'Errore durante l\'aggiornamento del carrello: {e}', 'danger')

    return redirect(url_for('cart'))

@app.route('/remove_from_cart/<int:product_id>/<int:taglia_id>', methods=['POST'])
def remove_from_cart(product_id, taglia_id):
    email = session.get('email')
    if not email:
        flash('Devi effettuare il login per rimuovere prodotti dal carrello.', 'danger')
        return redirect(url_for('login'))

    with engine.connect() as connection:
        try:
            transaction = connection.begin()
            connection.execute(
                text('''
                    DELETE FROM prodottiincarrello
                    WHERE carrello = (SELECT id FROM carrello WHERE utente = :utente)
                    AND prodotto = :product_id AND taglia = :taglia_id
                '''),
                {'utente': email, 'product_id': product_id, 'taglia_id': taglia_id}
            )
            transaction.commit()
            flash('Prodotto rimosso dal carrello.', 'success')
        except Exception as e:
            transaction.rollback()
            flash(f'Errore durante la rimozione del prodotto dal carrello: {e}', 'danger')

    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    email = session.get('email')

    if not email:
        flash('Devi effettuare il login per procedere al checkout.', 'danger')
        return redirect(url_for('login'))

    try:
        with engine.connect() as connection:
            # Recupera il carrello dell'utente
            carrello_result = connection.execute(
                text('SELECT id FROM carrello WHERE utente = :utente'),
                {'utente': email}
            ).fetchone()

            if not carrello_result:
                flash('Il tuo carrello è vuoto.', 'danger')
                return redirect(url_for('cart'))

            carrello_id = carrello_result[0]

            # Recupera gli articoli nel carrello con il calcolo del prezzo totale
            cart_items = connection.execute(
                text(''' 
                    SELECT pci.prodotto AS id_scarpa, p.nome, p.prezzo, pci.quantita, pci.taglia, i.percorso AS image_url, t.quantità AS stock
                    FROM prodottiincarrello pci
                    JOIN prodotto p ON pci.prodotto = p.id
                    LEFT JOIN immagini i ON p.id_immagine = i.id
                    JOIN taglie t ON t.id_scarpa = pci.prodotto AND t.taglia = pci.taglia
                    WHERE pci.carrello = :carrello_id
                '''), 
                {'carrello_id': carrello_id}
            ).fetchall()

            if not cart_items:
                flash('Il tuo carrello è vuoto.', 'danger')
                return redirect(url_for('cart'))

            # Calcola il prezzo totale del carrello
            total_price = 0
            for item in cart_items:
                total_price += item.prezzo * item.quantita  # Aggiungi il prezzo per ogni articolo (prezzo * quantità)

            # Recupera indirizzi e carte
            indirizzi = connection.execute(
                text('SELECT id, citta, via, numero, cap, provincia FROM indirizzo WHERE persona = :persona'),
                {'persona': email}
            ).fetchall()

            carte = connection.execute(
                text('SELECT id, numero, nome, cognome, datascadenza FROM carte WHERE persona = :persona'),
                {'persona': email}
            ).fetchall()

            # Gestione dei form di checkout (indirizzo e carta)
            if request.method == 'POST':
                # Recupero o creazione dell'indirizzo
                indirizzo_id = request.form.get('indirizzo')
                if not indirizzo_id:
                    citta = request.form.get('citta')
                    via = request.form.get('via')
                    numero = request.form.get('numero')
                    cap = request.form.get('cap')
                    provincia = request.form.get('provincia')

                    indirizzo_result = connection.execute(
                        text(''' 
                            INSERT INTO indirizzo (citta, via, numero, cap, provincia, persona) 
                            VALUES (:citta, :via, :numero, :cap, :provincia, :persona) 
                            RETURNING id 
                        '''), 
                        {'citta': citta, 'via': via, 'numero': numero, 'cap': cap, 'provincia': provincia, 'persona': email}
                    )
                    indirizzo_id = indirizzo_result.fetchone()[0]

                # Recupero o creazione della carta
                id_carta = request.form.get('carta')
                if not id_carta:
                    nome_carta = request.form.get('nome_carta')
                    cognome_carta = request.form.get('cognome_carta')
                    numero_carta = request.form.get('numero_carta')
                    datascadenza = request.form.get('datascadenza')

                    carta_result = connection.execute(
                        text(''' 
                            INSERT INTO carte (numero, nome, cognome, persona, datascadenza) 
                            VALUES (:numero, :nome, :cognome, :persona, :datascadenza) 
                            RETURNING id 
                        '''), 
                        {'numero': numero_carta, 'nome': nome_carta, 'cognome': cognome_carta, 'persona': email, 'datascadenza': datascadenza}
                    )
                    id_carta = carta_result.fetchone()[0]

                # Creazione dell'ordine
                ordine_result = connection.execute(
                    text(''' 
                        INSERT INTO ordini (dataacquisto, stato, indirizzospedizione, idcarrello, idcarta, pagato, dataprevista) 
                        VALUES (CURRENT_DATE, 'In elaborazione', :indirizzo_id, :carrello_id, :id_carta, FALSE, CURRENT_DATE + INTERVAL '3 days') 
                        RETURNING id 
                    '''), 
                    {'indirizzo_id': indirizzo_id, 'carrello_id': carrello_id, 'id_carta': id_carta}
                )
                ordine_id = ordine_result.fetchone()[0]

                # Inserimento prodotti in `prodottiinordine`
                for item in cart_items:
                    connection.execute(
                        text(''' 
                            INSERT INTO prodottiinordine (ordine, prodotto, quantita, taglia) 
                            VALUES (:ordine_id, :id_scarpa, :quantita, :taglia) 
                        '''), 
                        {
                            'ordine_id': ordine_id,
                            'id_scarpa': item.id_scarpa,
                            'quantita': item.quantita,
                            'taglia': item.taglia,
                        }
                    )

                    # Aggiornamento dello stock
                    connection.execute(
                        text(''' 
                            UPDATE taglie 
                            SET quantità = quantità - :quantita 
                            WHERE id_scarpa = :id_scarpa AND taglia = :taglia 
                        '''), 
                        {'quantita': item.quantita, 'id_scarpa': item.id_scarpa, 'taglia': item.taglia}
                    )

                # Rimuove i prodotti dal carrello
                connection.execute(
                    text('DELETE FROM prodottiincarrello WHERE carrello = :carrello_id'),
                    {'carrello_id': carrello_id}
                )
                connection.commit()

                flash('Ordine effettuato con successo! Riceverai aggiornamenti via email.', 'success')
                return redirect(url_for('order_confirmation'))

    except Exception as e:
        app.logger.error(f'Errore durante il checkout: {e}')
        flash('Errore imprevisto. Per favore riprova.', 'danger')

    return render_template(
        'checkout.html',
        cart=cart_items,
        total_price=total_price,  # Aggiungi il prezzo totale da passare al template
        indirizzi=indirizzi,
        carte=carte,
        mostra_indirizzo_form=session.get('mostra_indirizzo_form', False),
        mostra_carta_form=session.get('mostra_carta_form', False)
    )


@app.route('/order_confirmation', methods=['GET'])
def order_confirmation():
    
    session.pop('mostra_indirizzo_form', None)
    session.pop('mostra_carta_form', None)
    
    return render_template('order_confirmation.html')

# Rotta per il logout
@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('soprannome', None)
    session.clear()
    flash('Logout effettuato con successo.', 'success')
    return redirect(url_for('index'))

@app.route('/user_dashboard')
def user_dashboard():
    email = session.get('email')

    if not email:
        flash('Devi effettuare il login per accedere alla tua dashboard.', 'danger')
        return redirect(url_for('login'))

    with engine.connect() as connection:
        # Recupera gli ordini dell'utente
        ordini = connection.execute(
            text(''' 
                SELECT o.id, o.dataacquisto, o.stato, o.indirizzospedizione, 
                       o.dataprevista, c.prezzotot 
                FROM ordini o 
                JOIN carrello c ON o.idcarrello = c.id 
                WHERE c.utente = :email 
                ORDER BY o.dataacquisto DESC 
            '''), 
            {'email': email}
        ).fetchall()

        # Recupera i prodotti associati a ciascun ordine
        ordini_prodotti = {}
        for ordine in ordini:
            prodotti = connection.execute(
                text(''' 
                    SELECT p.id, p.nome, p.descrizione, p.prezzo, pi.quantita, pi.taglia 
                    FROM prodottiinordine pi 
                    JOIN prodotto p ON pi.prodotto = p.id 
                    WHERE pi.ordine = :ordine_id 
                '''), 
                {'ordine_id': ordine.id}
            ).fetchall()

            # Raggruppa i prodotti per prodotto.id
            prodotti_gruppati = {}
            for prodotto in prodotti:
                prodotto_id = prodotto.id
                if prodotto_id not in prodotti_gruppati:
                    prodotti_gruppati[prodotto_id] = {
                        'nome': prodotto.nome,
                        'descrizione': prodotto.descrizione,
                        'prezzo': prodotto.prezzo,
                        'taglie': [],
                        'quantita': 0
                    }
                # Aggiungi la taglia e la quantità
                prodotti_gruppati[prodotto_id]['taglie'].append(prodotto.taglia)
                prodotti_gruppati[prodotto_id]['quantita'] += prodotto.quantita

            ordini_prodotti[ordine.id] = prodotti_gruppati

        # Recupera i prodotti recensiti dall'utente
        prodotti_recensiti = connection.execute(
            text('SELECT prodotto FROM recensioni WHERE utente = :email'),
            {'email': email}
        ).fetchall()
        prodotti_recensiti = {row[0] for row in prodotti_recensiti}  # Crea un set di ID prodotto

    # Passa i dati alla dashboard
    return render_template('user_dashboard.html', ordini=ordini, ordini_prodotti=ordini_prodotti, prodotti_recensiti=prodotti_recensiti)

@app.route('/orders_received', methods=['GET', 'POST'])
def orders_received():
    email = session.get('email')

    if not email or not session.get('venditore'):
        flash('Devi effettuare il login come venditore per accedere a questa sezione.', 'danger')
        return redirect(url_for('login'))

    with engine.connect() as connection:
        # Query per ottenere tutti gli ordini ricevuti per i prodotti del venditore
        with engine.connect() as connection:
    # Query per ottenere tutti gli ordini ricevuti per i prodotti del venditore
            ordini = connection.execute(
                text('''
                    SELECT 
                        o.id, 
                        o.dataacquisto, 
                        o.stato, 
                        o.indirizzospedizione, 
                        o.dataprevista, 
                        c.utente
                    FROM ordini o
                    JOIN carrello c ON o.idcarrello = c.id
                    JOIN prodottiinordine poi ON o.id = poi.ordine
                    JOIN prodotto p ON poi.prodotto= p.id
                    WHERE p.venditore = :email
                    GROUP BY o.id, c.utente
                    ORDER BY o.dataacquisto DESC
                '''),
                {'email': email}
            ).fetchall()


    return render_template('orders_received.html', ordini=ordini)

@app.route('/orders_recensioni', methods=['GET', 'POST'])
def orders_recensioni():
    email = session.get('email')

    if not email or not session.get('venditore'):
        flash('Devi effettuare il login come venditore per accedere a questa sezione.', 'danger')
        return redirect(url_for('login'))

    with engine.connect() as connection:
        # Query per ottenere tutte le recensioni divise per prodotto e la media delle recensioni
        result = connection.execute(
            text(''' 
                SELECT 
                    p.id AS prodotto_id,
                    p.nome AS prodotto_nome,
                    AVG(r.stelle) AS media_stelle,  -- Calcolo della media delle stelle
                    r.id AS recensione_id,
                    r.stelle,
                    r.recensione AS commento
                FROM 
                    recensioni r
                JOIN prodotto p ON r.prodotto = p.id
                WHERE 
                    p.venditore = :email
                GROUP BY 
                    p.id, p.nome, r.id, r.stelle, r.recensione
                ORDER BY 
                    p.nome
            '''),
            {'email': email}
        ).fetchall()

        # Organizza le recensioni per prodotto in un dizionario
        recensioni_per_prodotto = {}
        for r in result:
            # Trasforma la tupla in un dizionario
            r_dict = dict(r._mapping)

            prodotto_id = r_dict['prodotto_id']
            prodotto_nome = r_dict['prodotto_nome']
            media_stelle = r_dict['media_stelle']
            recensione_id = r_dict['recensione_id']
            stelle = r_dict['stelle']
            commento = r_dict['commento']

            if prodotto_id not in recensioni_per_prodotto:
                recensioni_per_prodotto[prodotto_id] = {
                    'nome': prodotto_nome,
                    'media_stelle': media_stelle,  # Aggiunta della media delle stelle
                    'recensioni': []
                }

            recensioni_per_prodotto[prodotto_id]['recensioni'].append({
                'id': recensione_id,
                'stelle': stelle,
                'commento': commento,
            })

    return render_template('ordersrecensioni.html', recensioni_per_prodotto=recensioni_per_prodotto)

@app.route('/update_order_status/<int:ordine_id>', methods=['POST'])
def update_order_status(ordine_id):
    nuovo_stato = request.form.get('stato')
    print(f"Nuovo stato ricevuto: {nuovo_stato}")  # Debug per controllare il valore ricevuto

    if not nuovo_stato:
        flash('Errore: nessuno stato selezionato.', 'danger')
        return redirect(url_for('orders_received'))

    try:
        with engine.connect() as connection:
            transaction = connection.begin()

            try:
                # Aggiorna lo stato dell'ordine
                result = connection.execute(
                    text('UPDATE ordini SET stato = :nuovo_stato WHERE id = :ordine_id'),
                    {'nuovo_stato': nuovo_stato, 'ordine_id': ordine_id}
                )
                print(f"Righe aggiornate: {result.rowcount}")  # Debug per controllare le righe aggiornate

                if result.rowcount == 0:
                    flash('Errore: ordine non trovato o nessuna modifica applicata.', 'danger')
                    transaction.rollback()
                    return redirect(url_for('orders_received'))

                # Recupera l'email dell'utente che ha effettuato l'ordine
                utente_result = connection.execute(
                    text('''
                        SELECT c.utente
                        FROM ordini o
                        JOIN carrello c ON o.idcarrello = c.id
                        WHERE o.id = :ordine_id
                    '''),
                    {'ordine_id': ordine_id}
                ).fetchone()

                if utente_result:
                    utente_email = utente_result[0]  # Accedi al primo elemento della tupla
                    print(f"Invio messaggio a: {utente_email}")  # Debug per confermare l'email dell'utente

                    # Crea un messaggio per l'utente
                    titolo = "Aggiornamento dello stato dell'ordine"
                    testo = f"Il tuo ordine #{ordine_id} è stato aggiornato a '{nuovo_stato}'."

                    try:
                        # Inserimento del messaggio nel database
                        connection.execute(
                            text('''
                                INSERT INTO messaggi (destinatario, titolo, testo)
                                VALUES (:destinatario, :titolo, :testo)
                            '''),
                            {'destinatario': utente_email, 'titolo': titolo, 'testo': testo}
                        )
                        print("Messaggio inserito correttamente nel database.")  # Debug per confermare l'inserimento

                    except Exception as e:
                        print(f"Errore durante l'inserimento del messaggio: {e}")  # Messaggio di errore dettagliato

                else:
                    print("Errore: destinatario non trovato per questo ordine.")  # Debug per identificare l'errore

                transaction.commit()
                flash('Stato dell\'ordine aggiornato con successo e messaggio inviato all\'utente!', 'success')

            except Exception as e:
                transaction.rollback()
                print(f"Errore durante l'aggiornamento dello stato dell'ordine: {e}")  # Debug per errori generici
                flash(f'Errore durante l\'aggiornamento dello stato dell\'ordine: {e}', 'danger')

    except Exception as e:
        flash(f'Errore generale: {e}', 'danger')

    return redirect(url_for('orders_received'))


@app.route('/recensioni/<int:prodotto_id>', methods=['GET', 'POST'])
def recensioni(prodotto_id):
    email = session.get('email')

    if not email:
        flash('Devi effettuare il login per accedere alla sezione recensioni.', 'danger')
        return redirect(url_for('login'))

    with engine.connect() as connection:
        # Recupera i dettagli del prodotto
        prodotto = connection.execute(
            text('''
                SELECT p.id, p.nome, p.descrizione, p.prezzo, i.percorso AS immagine
                FROM prodotto p
                LEFT JOIN immagini i ON p.id_immagine = i.id
                WHERE p.id = :prodotto_id
            '''),
            {'prodotto_id': prodotto_id}
        ).fetchone()

        if not prodotto:
            flash('Il prodotto selezionato non esiste.', 'danger')
            return redirect(url_for('user_dashboard'))

    if request.method == 'POST':

        stelle = request.form.get('stelle')
        recensione = request.form.get('recensione')

        if not stelle or not recensione:
            flash('Devi completare tutti i campi per inviare la recensione.', 'danger')
        else:
            try:
                with engine.connect() as connection:
                    connection.execute(
                        text('''
                            INSERT INTO recensioni (utente, prodotto, recensione, stelle)
                            VALUES (:email, :prodotto_id, :recensione, :stelle)
                        '''),
                        {
                            'email': email,
                            'prodotto_id': prodotto_id,
                            'recensione': recensione,
                            'stelle': int(stelle)
                        }
                    )
                    connection.commit()
                flash('Recensione inviata con successo!', 'success')
                return redirect(url_for('user_dashboard'))
            except Exception as e:
                flash('Errore nell\'invio della recensione. Riprovare.', 'danger')

    return render_template('recensioni.html', prodotto=prodotto)


# route per la dashboard venditore
@app.route('/dashboard')
def dashboard():
    email = session.get('email')

    if not email:
        flash('Devi effettuare il login per accedere alla dashboard.', 'danger')
        return redirect(url_for('login'))

    with engine.connect() as connection:
        # Query per ottenere il numero totale di prodotti del venditore
        total_products_result = connection.execute(
            text('SELECT COUNT(*) FROM prodotto WHERE venditore = :email'),
            {'email': email}
        )
        total_products = total_products_result.scalar() or 0

        # Query per ottenere il numero totale di ordini ricevuti per i prodotti del venditore
        total_orders_result = connection.execute(
            text('''
                SELECT COUNT(DISTINCT o.id)  -- Conta solo ordini distinti
        FROM ordini o
        JOIN carrello c ON o.idcarrello = c.id
        JOIN prodottiinordine poi ON o.id = poi.ordine  -- Tabella che traccia i prodotti nell'ordine
        JOIN prodotto p ON poi.prodotto = p.id
        WHERE p.venditore = :email
            '''),
            {'email': email}
        )
        total_orders = total_orders_result.scalar() or 0

        # Query per ottenere la valutazione media dei prodotti
        avg_rating_result = connection.execute(
            text('''
                SELECT AVG(r.stelle)
                FROM recensioni r
                JOIN prodotto p ON r.prodotto = p.id
                WHERE p.venditore = :email
            '''),
            {'email': email}
        )
        avg_rating = round(avg_rating_result.scalar() or 0, 2)

        products_result = connection.execute(
            text(''' 
                SELECT 
                    p.id, 
                    p.nome, 
                    p.prezzo, 
                    COUNT(DISTINCT r.id) AS recensioni_count,  -- Conta solo recensioni uniche
                    ROUND(AVG(r.stelle), 2) AS avg_stelle,  -- Media arrotondata a 2 decimali
                    SUM(t.quantità) AS quantita
                FROM 
                    prodotto p
                LEFT JOIN recensioni r ON p.id = r.prodotto
                LEFT JOIN taglie t ON t.id_scarpa = p.id
                WHERE 
                    p.venditore = :email
                GROUP BY 
                    p.id
            '''),
            {'email': email}
        )
        products = products_result.fetchall()



    return render_template(
        'dashboard.html',
        total_products=total_products,
        total_orders=total_orders,
        avg_rating=avg_rating,
        products=products
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        soprannome = request.form['soprannome']
        ntelefono = request.form['ntelefono']
        nome = request.form['nome']
        cognome = request.form['cognome']
        datanascita = request.form['datanascita']
        codfiscale = request.form['codfiscale']
        venditore = request.form.get('venditore') == 'on'

        if len(password) < 8 or not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return render_template('register.html')

        # Hash della password
        hashed_password = generate_password_hash(password)

        try:
            with engine.connect() as connection:
                transaction = connection.begin()

                # Inserimento dell'utente nel database
                connection.execute(
                    text('''
                        INSERT INTO persona (email, password, soprannome, ntelefono, nome, cognome, datanascita, codfiscale, venditore) 
                        VALUES (:email, :password, :soprannome, :ntelefono, :nome, :cognome, :datanascita, :codfiscale, :venditore)
                    '''),
                    {
                        'email': email, 'password': hashed_password, 'soprannome': soprannome,
                        'ntelefono': ntelefono, 'nome': nome, 'cognome': cognome,
                        'datanascita': datanascita, 'codfiscale': codfiscale, 'venditore': venditore
                    }
                )

                # Creazione del carrello per l'utente
                connection.execute(
                    text('INSERT INTO carrello (utente) VALUES (:utente)'),
                    {'utente': email}
                )

                transaction.commit()

                # Impostazioni sessione
                session['soprannome'] = soprannome
                session['email'] = email
                session['venditore'] = venditore

                flash('Registrazione avvenuta con successo!', 'success')

                # Se è un venditore, reindirizza alla rotta dativenditore
                if venditore:
                    return redirect(url_for('dativenditore'))
                else:
                    return redirect(url_for('index'))

        except Exception as e:
            transaction.rollback()
            flash(f'Errore durante la registrazione: {str(e)}', 'danger')
            return render_template('register.html')

    return render_template('register.html')


@app.route('/dativenditore', methods=['GET', 'POST'])
def dativenditore():
    if request.method == 'POST':
        piva = request.form['piva']
        azienda = request.form['azienda']
        email = session.get('email')

        try:
            with engine.connect() as connection:
                transaction = connection.begin()

                print(f"Email: {email}, P.IVA: {piva}, Azienda: {azienda}")  # Debug
                
                # Inserimento delle informazioni aziendali per il venditore
                connection.execute(
                    text('''
                        INSERT INTO dativenditori (persona, piva, azienda)
                        VALUES (:persona, :piva, :azienda)
                    '''),
                    {'persona': email, 'piva': piva, 'azienda': azienda}
                )

                transaction.commit()

                # Aggiungi i dati alla sessione
                session['piva'] = piva
                session['azienda'] = azienda

                flash('Dati del venditore salvati con successo!', 'success')
                return redirect(url_for('index'))

        except Exception as e:
            transaction.rollback()
            flash(f'Errore durante il salvataggio dei dati: {str(e)}', 'danger')

    return render_template('dativenditore.html')




@app.route('/sell', methods=['GET', 'POST'])
def sell():
    if 'email' not in session:
        session['attempt_sell'] = True
        return redirect(url_for('login'))

    email = session['email']  # Prendi l'email dell'utente loggato

    with engine.connect() as connection:
        resultc = connection.execute(text('SELECT id, nome FROM categoria'))
        categorie = resultc.fetchall()

    if request.method == 'POST':
        nome = request.form['nome']
        colore = request.form['colore']
        prezzo = request.form['prezzo']
        descrizione = request.form['descrizione']
        venditore = email
        categoria = request.form['categoria']

        # Gestione delle immagini
        immagini = request.files.getlist('immagine')
        percorsi_immagini = []
        immagine_ids = []

        try:
            with engine.connect() as connection:
                transaction = connection.begin()

                # Inserimento del prodotto
                result = connection.execute(
                    text('''
                        INSERT INTO prodotto (nome, prezzo, descrizione, venditore, categoria, colore)
                        VALUES (:nome, :prezzo, :descrizione, :venditore, :categoria, :colore)
                        RETURNING id
                    '''),
                    {'nome': nome, 'prezzo': prezzo, 'descrizione': descrizione,
                     'venditore': venditore, 'categoria': categoria, 'colore': colore}
                )
                prodotto_id = result.fetchone()[0]

                # Gestione delle immagini
                for immagine in immagini:
                    if immagine:
                        percorso = f'static/uploads/{immagine.filename}'
                        immagine.save(percorso)
                        percorsi_immagini.append(percorso)

                        # Inserisci il percorso e il formato nel database delle immagini
                        result_img = connection.execute(
                            text('''
                                INSERT INTO immagini (percorso, formato) 
                                VALUES (:percorso, :formato)
                                RETURNING id
                            '''),
                            {'percorso': percorso, 'formato': immagine.content_type}
                        )
                        immagine_id = result_img.fetchone()[0]
                        immagine_ids.append(immagine_id)

                # Collega l'immagine principale
                if immagine_ids:
                    connection.execute(
                        text('''
                            UPDATE prodotto
                            SET id_immagine = :id_immagine
                            WHERE id = :id_prodotto
                        '''),
                        {'id_immagine': immagine_ids[0], 'id_prodotto': prodotto_id}
                    )

                # Gestione delle taglie e delle quantità
                taglie = request.form.getlist('taglia[]')
                quantita = request.form.getlist('quantità[]')

                for taglia, qta in zip(taglie, quantita):
                    connection.execute(
                        text('''
                            INSERT INTO taglie (taglia, id_scarpa, quantità)
                            VALUES (:taglia, :id_scarpa, :quantità)
                        '''),
                        {'taglia': int(taglia), 'id_scarpa': prodotto_id, 'quantità': int(qta)}
                    )

                transaction.commit()
                
                result = connection.execute(text('SELECT * FROM prodotto'))
                # Query per ottenere tutte le categorie dal database
                resultc = connection.execute(text('SELECT * FROM categoria'))

                prodotti = result.fetchall()
                categorie = resultc.fetchall()  # Cambia il nome da 'categoria' a 'categorie' per chiarezza

                 # Passa i prodotti e le categorie al template
                return render_template('index.html', prodotti=prodotti, categorie=categorie)

        except Exception as e:
            if 'transaction' in locals():
                transaction.rollback()
            flash(f'Errore durante l\'aggiunta del prodotto: {str(e)}', 'danger')
            print(f"Errore: {e}")  # Debug

        pass

    return render_template('sell.html', prodotto=None, email=email, categorie=categorie)


@app.route('/product/<int:product_id>', methods=['GET'])
def product_details(product_id):
    with engine.connect() as connection:
        email = session.get('email')
        # Recupera i dettagli del prodotto
        prodotto_query = """
        SELECT p.*, i.percorso AS immagine 
        FROM prodotto p 
        LEFT JOIN immagini i ON p.id_immagine = i.id 
        WHERE p.id = :product_id
        """
        prodotto_result = connection.execute(text(prodotto_query), {'product_id': product_id})
        prodotto_row = prodotto_result.fetchone()

        if prodotto_row is None:
            flash('Prodotto non trovato', 'danger')
            return redirect(url_for('products'))

        prodotto = dict(prodotto_row._mapping)

        # Recupera le immagini del prodotto
        immagini_query = """
        SELECT percorso 
        FROM immagini 
        WHERE id IN (
            SELECT id_immagine 
            FROM prodotto 
            WHERE id = :product_id
        )
        """
        immagini_result = connection.execute(text(immagini_query), {'product_id': product_id})
        immagini = [row[0] for row in immagini_result.fetchall()]

        # Recupera le taglie disponibili
        taglie_query = "SELECT taglia FROM taglie WHERE id_scarpa = :product_id AND quantità > 0"
        taglie_result = connection.execute(text(taglie_query), {'product_id': product_id})
        taglie_disponibili = [row[0] for row in taglie_result.fetchall()]

        # Recupera le recensioni associate al prodotto
        recensioni_query = """
        SELECT r.recensione, r.stelle, r.utente, p.soprannome
        FROM recensioni r
        JOIN persona p ON r.utente = p.email
        WHERE r.prodotto = :product_id
        ORDER BY r.stelle DESC
        """
        recensioni_result = connection.execute(text(recensioni_query), {'product_id': product_id})
        recensioni = [dict(row._mapping) for row in recensioni_result.fetchall()]

        # Calcola la media delle stelle per le recensioni del prodotto
        media_stelle_query = """
        SELECT AVG(stelle) AS media_stelle
        FROM recensioni
        WHERE prodotto = :product_id
        """
        media_stelle_result = connection.execute(text(media_stelle_query), {'product_id': product_id})
        media_stelle_row = media_stelle_result.fetchone()

        if media_stelle_row is not None:
            media_stelle = media_stelle_row[0]  # Accesso al valore della media delle stelle
        else:
            media_stelle = None

        return render_template(
            'product_details.html',
            email=email,
            prodotto=prodotto,
            immagini=immagini,
            taglie_disponibili=taglie_disponibili,
            recensioni=recensioni,
            media_stelle=media_stelle
        )


@app.route('/products', methods=['GET', 'POST'])
def products():
    filters = {}
    query = """
        SELECT DISTINCT ON (p.id) p.*, i.percorso as image_url
        FROM prodotto p
        LEFT JOIN taglie t ON p.id = t.id_scarpa
        LEFT JOIN immagini i ON p.id_immagine = i.id
        WHERE 1=1
    """
    
    # Parametri di filtro
    categoria = request.args.get('categoria_id')
    taglia = request.args.get('taglia')
    colore = request.args.get('colore')
    prezzo_min = request.args.get('prezzo_min')
    prezzo_max = request.args.get('prezzo_max')
    
    # Filtro per categoria
    if categoria:
        query += " AND p.categoria = :categoria"
        filters['categoria'] = categoria
    
    # Filtro per taglia
    if taglia:
        query += " AND t.taglia = :taglia"
        filters['taglia'] = taglia

    # Filtro per colore
    if colore:
        query += " AND p.colore = :colore"
        filters['colore'] = colore
    
    # Filtro per prezzo
    if prezzo_min:
        query += " AND p.prezzo >= :prezzo_min"
        filters['prezzo_min'] = prezzo_min
    
    if prezzo_max:
        query += " AND p.prezzo <= :prezzo_max"
        filters['prezzo_max'] = prezzo_max

    # Esegui la query con i filtri
    with engine.connect() as connection:
        result = connection.execute(text(query), filters)
        prodotti = result.fetchall()

        # Ottieni le categorie, taglie e colori disponibili
        categorie = connection.execute(text("SELECT * FROM categoria")).fetchall()
        taglie = connection.execute(text("SELECT DISTINCT taglia FROM taglie")).fetchall()
        colori = connection.execute(text("SELECT DISTINCT colore FROM prodotto")).fetchall()

    return render_template('products.html', 
                           prodotti=prodotti, 
                           categorie=categorie, 
                           taglie=taglie, 
                           colori=colori, 
                           categoria_selezionata=categoria, 
                           taglia_selezionata=taglia, 
                           colore_selezionato=colore, 
                           prezzo_min=prezzo_min, 
                           prezzo_max=prezzo_max)


@app.route('/user_profile', methods=['GET', 'POST'])
def user_profile():
    email = session.get('email')
    
    if request.method == 'POST':
        # Dati base
        new_email = request.form.get('email')
        new_soprannome = request.form.get('soprannome')
        new_immagine = request.files.get('immagine')
        
        # Dati indirizzo
        new_citta = request.form.get('citta')
        new_via = request.form.get('via')
        new_numero = request.form.get('numero')
        new_cap = request.form.get('cap')
        new_provincia = request.form.get('provincia')
        
        # Dati carta di credito
        new_numero_carta = request.form.get('numero_carta')
        new_datascadenza = request.form.get('datascadenza')
        new_cvv = request.form.get('cvv')
        new_nome_carta = request.form.get('nome_carta')
        new_cognome_carta = request.form.get('cognome_carta')

        try:
            with engine.connect() as connection:
                transaction = connection.begin()

                # Aggiornamento email
                if new_email and new_email != email:
                    connection.execute(
                        text('UPDATE persona SET email = :new_email WHERE email = :current_email'),
                        {'new_email': new_email, 'current_email': email}
                    )
                    email = new_email


                # Aggiornamento soprannome
                if new_soprannome:
                    connection.execute(
                        text('UPDATE persona SET soprannome = :new_soprannome WHERE email = :email'),
                        {'new_soprannome': new_soprannome, 'email': email}
                    )

                # Aggiornamento immagine
                if new_immagine and new_immagine.filename:
                    image_path = f'img/{new_immagine.filename}'
                    new_immagine.save(image_path)
                    connection.execute(
                        text('INSERT INTO immagini (percorso, formato) VALUES (:percorso, :formato) RETURNING id'),
                        {'percorso': image_path, 'formato': new_immagine.content_type}
                    )
                    image_id = connection.execute(text('SELECT LASTVAL()')).scalar()
                    connection.execute(
                        text('UPDATE persona SET immagine = :image_id WHERE email = :email'),
                        {'image_id': image_id, 'email': email}
                    )

                # Aggiornamento indirizzo
                if new_citta and new_via and new_numero and new_cap and new_provincia:
                    existing_address = connection.execute(
                        text('SELECT 1 FROM indirizzo WHERE persona = :email'),
                        {'email': email}
                    ).fetchone()
                    
                    if existing_address:
                        connection.execute(
                            text('UPDATE indirizzo SET citta = :citta, via = :via, numero = :numero, cap = :cap, provincia = :provincia WHERE persona = :email'),
                            {'citta': new_citta, 'via': new_via, 'numero': new_numero, 'cap': new_cap, 'provincia': new_provincia, 'email': email}
                        )
                    else:
                        connection.execute(
                            text('INSERT INTO indirizzo (citta, via, numero, cap, provincia, persona) VALUES (:citta, :via, :numero, :cap, :provincia, :persona)'),
                            {'citta': new_citta, 'via': new_via, 'numero': new_numero, 'cap': new_cap, 'provincia': new_provincia, 'persona': email}
                        )

                # Aggiornamento carta di credito
                if new_numero_carta and new_datascadenza and new_cvv and new_nome_carta and new_cognome_carta:
                    existing_card = connection.execute(
                        text('SELECT 1 FROM carte WHERE persona = :email'),
                        {'email': email}
                    ).fetchone()
                    
                    if existing_card:
                        connection.execute(
                            text('UPDATE carte SET numero = :numero_carta, datascadenza = :datascadenza, cvv = :cvv, nome = :nome_carta, cognome = :cognome_carta WHERE persona = :email'),
                            {'numero_carta': new_numero_carta, 'datascadenza': new_datascadenza, 'cvv': new_cvv, 'nome_carta': new_nome_carta, 'cognome_carta': new_cognome_carta, 'email': email}
                        )
                    else:
                        connection.execute(
                            text('INSERT INTO carte (persona, numero, datascadenza, cvv, nome, cognome) VALUES (:persona, :numero_carta, :datascadenza, :cvv, :nome_carta, :cognome_carta)'),
                            {'persona': email, 'numero_carta': new_numero_carta, 'datascadenza': new_datascadenza, 'cvv': new_cvv, 'nome_carta': new_nome_carta, 'cognome_carta': new_cognome_carta}
                        )

                transaction.commit()
                flash('Profilo aggiornato con successo!', 'success')
        except Exception as e:
            transaction.rollback()
            flash(f'Errore durante l\'aggiornamento del profilo: {e}', 'danger')

    # Recupero dati per il form
    try:
        with engine.connect() as connection:
            user_data = connection.execute(
                text('SELECT password, soprannome, immagine FROM persona WHERE email = :email'),
                {'email': email}
            ).fetchone()
            password, soprannome, immagine_id = user_data

            immagine = None
            if immagine_id:
                immagine_path = connection.execute(
                    text('SELECT percorso FROM immagini WHERE id = :immagine_id'),
                    {'immagine_id': immagine_id}
                ).fetchone()
                immagine = immagine_path[0] if immagine_path else None

            address_data = connection.execute(
                text('SELECT citta, via, numero, cap, provincia FROM indirizzo WHERE persona = :email'),
                {'email': email}
            ).fetchone()
            citta, via, numero, cap, provincia = address_data if address_data else (None, None, None, None, None)

            card_data = connection.execute(
                text('SELECT numero, datascadenza, cvv, nome, cognome FROM carte WHERE persona = :email'),
                {'email': email}
            ).fetchone()
            numero_carta, datascadenza, cvv, nome_carta, cognome_carta = card_data if card_data else (None, None, None, None, None)

    except Exception as e:
        flash(f'Errore nel recupero dei dati: {e}', 'danger')
        return redirect(url_for('login'))

    return render_template('user_profile.html', email=email, password=password, soprannome=soprannome, immagine=immagine,
                           citta=citta, via=via, numero=numero, cap=cap, provincia=provincia,
                           numero_carta=numero_carta, datascadenza=datascadenza, cvv=cvv, nome_carta=nome_carta, cognome_carta=cognome_carta)

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '').strip()  # Recupera la query dall'input dell'utente

    if not query:
        flash('Inserisci una parola chiave per effettuare la ricerca.', 'warning')
        return redirect(url_for('products'))

    # Costruisci la query di ricerca
    sql_query = """
        SELECT p.*, i.percorso as image_url
        FROM prodotto p
        LEFT JOIN immagini i ON p.id_immagine = i.id
        WHERE LOWER(p.nome) LIKE :query OR LOWER(p.descrizione) LIKE :query OR
              p.categoria IN (SELECT id FROM categoria WHERE LOWER(nome) LIKE :query)
    """

    query_param = f"%{query.lower()}%"

    with engine.connect() as connection:
        result = connection.execute(text(sql_query), {'query': query_param})
        prodotti = result.fetchall()

    if not prodotti:
        flash('Nessun prodotto trovato per la ricerca effettuata.', 'info')

    return render_template('products.html', prodotti=prodotti)


@app.route('/delete_product/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    if 'email' not in session or not session['venditore']:
        flash('Devi effettuare il login come venditore per eliminare un prodotto.', 'danger')
        return redirect(url_for('login'))

    try:
        with engine.connect() as connection:
            transaction = connection.begin()

            # 1. Elimina le recensioni associate al prodotto
            connection.execute(
                text('DELETE FROM recensioni WHERE prodotto = :product_id'),
                {'product_id': product_id}
            )

            # 2. Elimina il prodotto dalla tabella prodottiincarrello
            connection.execute(
                text('DELETE FROM prodottiincarrello WHERE prodotto = :product_id'),
                {'product_id': product_id}
            )

            # 3. Controlla e rimuovi i riferimenti negli ordini (se necessario)
            # Se il prodotto è parte di un carrello collegato a un ordine, potresti voler gestire diversamente la logica degli ordini.

            # 4. Elimina le taglie associate al prodotto
            connection.execute(
                text('DELETE FROM taglie WHERE id_scarpa = :product_id'),
                {'product_id': product_id}
            )

            # 5. Elimina il prodotto dalla tabella prodotto
            connection.execute(
                text('DELETE FROM prodotto WHERE id = :product_id'),
                {'product_id': product_id}
            )

            transaction.commit()
            flash('Prodotto eliminato con successo!', 'success')

    except Exception as e:
        if 'transaction' in locals() and transaction.is_active:
            transaction.rollback()
        flash(f'Errore durante l\'eliminazione del prodotto: {e}', 'danger')

    return redirect(url_for('dashboard'))

@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    email = session.get('email')
    if not email:
        flash('Devi effettuare il login per modificare un prodotto.', 'danger')
        return redirect(url_for('login'))

    with engine.connect() as connection:
        if request.method == 'POST':
            nome = request.form['nome']
            colore = request.form['colore']
            prezzo = request.form['prezzo']
            descrizione = request.form['descrizione']
            categoria = request.form['categoria']
            
            # Esegui la query di aggiornamento
            connection.execute(
                text('UPDATE prodotto SET nome = :nome, colore = :colore, prezzo = :prezzo, descrizione = :descrizione, categoria = :categoria WHERE id = :product_id AND venditore = :email'),
                {'nome': nome, 'colore': colore, 'prezzo': prezzo, 'descrizione': descrizione, 'categoria': categoria, 'product_id': product_id, 'email': email}
            )

            # Esegui il commit delle modifiche
            connection.commit()

            flash('Prodotto modificato con successo!', 'success')
            return redirect(url_for('dashboard'))

        # Recupera il prodotto specifico del venditore per visualizzarlo nel form di modifica
        prodotto = connection.execute(
            text('SELECT * FROM prodotto WHERE id = :product_id AND venditore = :email'),
            {'product_id': product_id, 'email': email}
        ).fetchone()

        if not prodotto:
            flash('Prodotto non trovato o non sei autorizzato a modificarlo.', 'danger')
            return redirect(url_for('dashboard'))

        # Recupera tutte le immagini associate al prodotto
        immagini = connection.execute(
            text('''
                SELECT percorso 
                FROM immagini 
                WHERE id IN (
                    SELECT id_immagine 
                    FROM prodotto 
                    WHERE id = :product_id
                )
            '''),
            {'product_id': product_id}
        ).fetchall()

        immagini = [row[0] for row in immagini]  # Converte le righe in una lista di percorsi

        # Recupera le taglie e le quantità associate al prodotto
        taglie = connection.execute(
            text('SELECT taglia, quantità FROM taglie WHERE id_scarpa = :product_id'),
            {'product_id': product_id}
        ).fetchall()

        # Recupera tutte le categorie per la selezione
        categorie = connection.execute(text('SELECT * FROM categoria')).fetchall()

    return render_template('sell.html', prodotto=prodotto, immagini=immagini, taglie=taglie, categorie=categorie, email=email)

@app.context_processor
def inject_messages():
    if 'email' in session:
        email = session['email']
        with engine.connect() as connection:
            messaggi = connection.execute(
                text('SELECT titolo, testo, data FROM messaggi WHERE destinatario = :email ORDER BY data DESC'),
                {'email': email}
            ).fetchall()
        return {'messaggi': messaggi}
    return {'messaggi': []}

from werkzeug.security import generate_password_hash, check_password_hash

def is_admin(email):
    with engine.connect() as connection:
        admin_exists = connection.execute(text("""
            SELECT * FROM amministratori WHERE amm_email = :email
        """), {'email': email}).scalar()
        return admin_exists is not None



@app.route('/admin', methods=['GET', 'POST'])
def admin_page():
    email = session.get('email')

    # Controllo permessi admin
    if not email or not is_admin(email):
        #flash('Accesso non autorizzato. Solo gli admin possono visualizzare questa pagina.', 'danger')
        return redirect(url_for('login'))

    # Recupero dati
    try:
        with engine.connect() as connection:
            # Statistiche
            user_count = connection.execute(text('SELECT COUNT(*) FROM persona')).scalar()
            seller_count = connection.execute(text('SELECT COUNT(*) FROM persona WHERE venditore = TRUE')).scalar()
            normal_user_count = connection.execute(text('SELECT COUNT(*) FROM persona WHERE venditore = FALSE')).scalar()
            order_count = connection.execute(text('SELECT COUNT(*) FROM ordini')).scalar()
            shoe_count = connection.execute(text('SELECT COUNT(*) FROM prodotto')).scalar()

            # Dettagli utenti
            users = connection.execute(text("""
    SELECT 
        p.email, 
        p.nome, 
        p.cognome, 
        p.venditore, 
        p.datanascita, 
        p.codfiscale, 
        dv.azienda, 
        dv.piva
    FROM persona p
    LEFT JOIN dativenditori dv ON p.email = dv.persona
""")).fetchall()


            # Dettagli ordini (incluso indirizzo di spedizione completo)
            orders = connection.execute(text('''
             SELECT 
    o.id AS order_id,
    p.email AS user_email,
    pr.nome AS shoe_name,
    pr.prezzo AS shoe_price,
    poi.quantita AS quantity,
    o.dataacquisto AS order_date,
    o.stato AS status,
    CONCAT(i.via, ' ', i.numero, ', ', i.citta, ' ', i.cap, ' - ', i.provincia) AS shipping_address,
    o.pagato AS paid,
    v.email AS seller_email,
    dv.azienda AS seller_company
FROM ordini o
INNER JOIN carrello c ON o.idcarrello = c.id
INNER JOIN persona p ON c.utente = p.email
INNER JOIN prodottiinordine poi ON o.id = poi.ordine
INNER JOIN prodotto pr ON poi.prodotto = pr.id
LEFT JOIN indirizzo i ON CAST(o.indirizzospedizione AS integer) = i.id
LEFT JOIN persona v ON pr.venditore = v.email
LEFT JOIN dativenditori dv ON v.email = dv.persona
ORDER BY o.dataacquisto DESC;




            ''')).fetchall()

            # Dettagli scarpe
            shoes = connection.execute(text('''
                SELECT 
                    pr.id AS product_id,
                    pr.nome AS shoe_name,
                    pr.prezzo AS shoe_price,
                    pr.descrizione AS description,
                    pr.colore AS color,
                    c.nome AS category_name,
                    COALESCE(SUM(t.quantità), 0) AS available_quantity
                FROM prodotto pr
                INNER JOIN categoria c ON pr.categoria = c.id
                LEFT JOIN taglie t ON pr.id = t.id_scarpa
                GROUP BY pr.id, c.nome;
            ''')).fetchall()
    except Exception as e:
        flash(f'Errore nel caricamento dei dati: {e}', 'danger')
        user_count = seller_count = normal_user_count = order_count = shoe_count = 0
        users = orders = shoes = []

    return render_template(
        'admin.html',
        user_count=user_count,
        seller_count=seller_count,
        normal_user_count=normal_user_count,
        order_count=order_count,
        shoe_count=shoe_count,
        users=users,
        orders=orders,
        shoes=shoes
    )







@app.route('/admin/add_admin', methods=['POST'])
def add_admin():
    admin_email = request.form.get('admin_email')
    admin_password = request.form.get('admin_password')

    if admin_email and admin_password:
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                # Genera hash della password
                password_hash = generate_password_hash(admin_password)
                # Inserisce l'admin nella tabella `amministratori`
                connection.execute(
                    text('INSERT INTO amministratori (amm_email, amm_password) VALUES (:email, :hash)'),
                    {'email': admin_email, 'hash': password_hash}
                )
                transaction.commit()
                flash('Nuovo amministratore aggiunto con successo!', 'success')
        except Exception as e:
            if 'transaction' in locals() and transaction.is_active:
                transaction.rollback()
            flash(f'Errore durante l\'aggiunta dell\'amministratore: {e}', 'danger')
    else:
        flash('Devi fornire email e password per creare un amministratore.', 'warning')

    return redirect(url_for('admin_page'))


@app.route('/admin/add_category', methods=['POST'])
def add_category():
    category_name = request.form.get('category_name')
    category_image = request.files.get('category_image')

    if category_name and category_image and category_image.filename:
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                filename = secure_filename(category_image.filename)
                filepath = os.path.join('static/uploads/', filename)
                category_image.save(filepath)
                # Inserimento dell'immagine
                result = connection.execute(
                    text('INSERT INTO immagini (percorso, formato) VALUES (:percorso, :formato) RETURNING id'),
                    {'percorso': filepath, 'formato': category_image.mimetype}
                )
                image_id = result.scalar()
                # Inserimento della categoria
                connection.execute(
                    text('INSERT INTO categoria (nome, id_immagine) VALUES (:nome, :id_immagine)'),
                    {'nome': category_name, 'id_immagine': image_id}
                )
                transaction.commit()
                flash('Categoria aggiunta con successo!', 'success')
        except Exception as e:
            if 'transaction' in locals() and transaction.is_active:
                transaction.rollback()
            flash(f'Errore durante l\'aggiunta della categoria: {e}', 'danger')
    else:
        flash('Tutti i campi sono obbligatori per aggiungere una categoria!', 'warning')

    return redirect(url_for('admin_page'))

@app.route('/admin/users', methods=['GET'])
def admin_users():
    # Controlla se l'utente è loggato come admin, se necessario
    # if not session.get('email') or not session.get('venditore'):
    #     return redirect(url_for('login'))

    try:
        with engine.connect() as connection:
            result = connection.execute(
                text('SELECT email, password, ntelefono, soprannome, venditore, nome, cognome, datanascita, codfiscale FROM persona')
            ).fetchall()
            # result è una lista di tuple, le trasformiamo in un elenco di dict per comodità
            users = []
            for row in result:
                users.append({
                    'email': row.email,
                    'password': row.password,
                    'ntelefono': row.ntelefono,
                    'soprannome': row.soprannome,
                    'venditore': row.venditore,
                    'nome': row.nome,
                    'cognome': row.cognome,
                    'datanascita': row.datanascita,
                    'codfiscale': row.codfiscale
                })
    except Exception as e:
        flash(f'Errore nel caricamento degli utenti: {e}', 'danger')
        users = []

    return render_template('admin_users.html', users=users)

@app.route('/admin/orders', methods=['GET'])
def admin_orders():
 # Recupero dati
    try:
        with engine.connect() as connection:
            # Statistiche
            user_count = connection.execute(text('SELECT COUNT(*) FROM persona')).scalar()
            seller_count = connection.execute(text('SELECT COUNT(*) FROM persona WHERE venditore = TRUE')).scalar()
            normal_user_count = connection.execute(text('SELECT COUNT(*) FROM persona WHERE venditore = FALSE')).scalar()
            order_count = connection.execute(text('SELECT COUNT(*) FROM ordini')).scalar()
            shoe_count = connection.execute(text('SELECT COUNT(*) FROM prodotto')).scalar()

            # Dettagli utenti
            users = connection.execute(text("""
    SELECT 
        p.email, 
        p.nome, 
        p.cognome, 
        p.venditore, 
        p.datanascita, 
        p.codfiscale, 
        dv.azienda, 
        dv.piva
    FROM persona p
    LEFT JOIN dativenditori dv ON p.email = dv.persona
""")).fetchall()


            # Dettagli ordini (incluso indirizzo di spedizione completo)
            orders = connection.execute(text('''
             SELECT 
    o.id AS order_id,
    p.email AS user_email,
    pr.nome AS shoe_name,
    pr.prezzo AS shoe_price,
    poi.quantita AS quantity,
    o.dataacquisto AS order_date,
    o.stato AS status,
    CONCAT(i.via, ' ', i.numero, ', ', i.citta, ' ', i.cap, ' - ', i.provincia) AS shipping_address,
    o.pagato AS paid,
    v.email AS seller_email,
    dv.azienda AS seller_company
FROM ordini o
INNER JOIN carrello c ON o.idcarrello = c.id
INNER JOIN persona p ON c.utente = p.email
INNER JOIN prodottiinordine poi ON o.id = poi.ordine
INNER JOIN prodotto pr ON poi.prodotto = pr.id
LEFT JOIN indirizzo i ON CAST(o.indirizzospedizione AS integer) = i.id
LEFT JOIN persona v ON pr.venditore = v.email
LEFT JOIN dativenditori dv ON v.email = dv.persona
ORDER BY o.dataacquisto DESC;




            ''')).fetchall()

            # Dettagli scarpe
            shoes = connection.execute(text('''
                SELECT 
                    pr.id AS product_id,
                    pr.nome AS shoe_name,
                    pr.prezzo AS shoe_price,
                    pr.descrizione AS description,
                    pr.colore AS color,
                    c.nome AS category_name,
                    COALESCE(SUM(t.quantità), 0) AS available_quantity
                FROM prodotto pr
                INNER JOIN categoria c ON pr.categoria = c.id
                LEFT JOIN taglie t ON pr.id = t.id_scarpa
                GROUP BY pr.id, c.nome;
            ''')).fetchall()
    except Exception as e:
        flash(f'Errore nel caricamento dei dati: {e}', 'danger')
        user_count = seller_count = normal_user_count = order_count = shoe_count = 0
        users = orders = shoes = []

    return render_template(
        'admin_orders.html',
        user_count=user_count,
        seller_count=seller_count,
        normal_user_count=normal_user_count,
        order_count=order_count,
        shoe_count=shoe_count,
        users=users,
        orders=orders,
        shoes=shoes
    )
    
    
@app.route('/admin/shoes', methods=['GET'])
def admin_shoes():
 # Recupero dati
    try:
        with engine.connect() as connection:
            # Statistiche
            user_count = connection.execute(text('SELECT COUNT(*) FROM persona')).scalar()
            seller_count = connection.execute(text('SELECT COUNT(*) FROM persona WHERE venditore = TRUE')).scalar()
            normal_user_count = connection.execute(text('SELECT COUNT(*) FROM persona WHERE venditore = FALSE')).scalar()
            order_count = connection.execute(text('SELECT COUNT(*) FROM ordini')).scalar()
            shoe_count = connection.execute(text('SELECT COUNT(*) FROM prodotto')).scalar()

            # Dettagli utenti
            users = connection.execute(text("""
    SELECT 
        p.email, 
        p.nome, 
        p.cognome, 
        p.venditore, 
        p.datanascita, 
        p.codfiscale, 
        dv.azienda, 
        dv.piva
    FROM persona p
    LEFT JOIN dativenditori dv ON p.email = dv.persona
""")).fetchall()


            # Dettagli ordini (incluso indirizzo di spedizione completo)
            orders = connection.execute(text('''
             SELECT 
    o.id AS order_id,
    p.email AS user_email,
    pr.nome AS shoe_name,
    pr.prezzo AS shoe_price,
    poi.quantita AS quantity,
    o.dataacquisto AS order_date,
    o.stato AS status,
    CONCAT(i.via, ' ', i.numero, ', ', i.citta, ' ', i.cap, ' - ', i.provincia) AS shipping_address,
    o.pagato AS paid,
    v.email AS seller_email,
    dv.azienda AS seller_company
FROM ordini o
INNER JOIN carrello c ON o.idcarrello = c.id
INNER JOIN persona p ON c.utente = p.email
INNER JOIN prodottiinordine poi ON o.id = poi.ordine
INNER JOIN prodotto pr ON poi.prodotto = pr.id
LEFT JOIN indirizzo i ON CAST(o.indirizzospedizione AS integer) = i.id
LEFT JOIN persona v ON pr.venditore = v.email
LEFT JOIN dativenditori dv ON v.email = dv.persona
ORDER BY o.dataacquisto DESC;




            ''')).fetchall()

            # Dettagli scarpe
            shoes = connection.execute(text('''
                SELECT 
                    pr.id AS product_id,
                    pr.nome AS shoe_name,
                    pr.prezzo AS shoe_price,
                    pr.descrizione AS description,
                    pr.colore AS color,
                    c.nome AS category_name,
                    COALESCE(SUM(t.quantità), 0) AS available_quantity
                FROM prodotto pr
                INNER JOIN categoria c ON pr.categoria = c.id
                LEFT JOIN taglie t ON pr.id = t.id_scarpa
                GROUP BY pr.id, c.nome;
            ''')).fetchall()
    except Exception as e:
        flash(f'Errore nel caricamento dei dati: {e}', 'danger')
        user_count = seller_count = normal_user_count = order_count = shoe_count = 0
        users = orders = shoes = []

    return render_template(
        'admin_shoes.html',
        user_count=user_count,
        seller_count=seller_count,
        normal_user_count=normal_user_count,
        order_count=order_count,
        shoe_count=shoe_count,
        users=users,
        orders=orders,
        shoes=shoes
    )


@app.route('/admin/delete_user/<email>', methods=['POST'])
def delete_user(email):
    try:
        with engine.connect() as connection:
            transaction = connection.begin()

            #  Cancella tutte le recensioni dell'utente
            connection.execute(text('DELETE FROM recensioni WHERE utente = :email'), {'email': email})

            #  Elimina prima i prodotti presenti nei carrelli dell'utente
            connection.execute(
                text('DELETE FROM prodottiincarrello WHERE carrello IN (SELECT id FROM carrello WHERE utente = :email)'),
                {'email': email}
            )

            #  Ottieni gli ID degli ordini associati al carrello dell'utente
            result = connection.execute(
                text('SELECT id FROM ordini WHERE idcarrello IN (SELECT id FROM carrello WHERE utente = :email)'),
                {'email': email}
            )
            order_ids = [row[0] for row in result]

            #  Se ci sono ordini, elimina prima i prodotti negli ordini e poi gli ordini stessi
            if order_ids:
                connection.execute(
                    text('DELETE FROM prodottiinordine WHERE ordine = ANY(:order_ids)'),
                    {'order_ids': order_ids}
                )
                connection.execute(
                    text('DELETE FROM ordini WHERE id = ANY(:order_ids)'),
                    {'order_ids': order_ids}
                )

            #  Ora possiamo eliminare i carrelli dell'utente
            connection.execute(text('DELETE FROM carrello WHERE utente = :email'), {'email': email})

            #  Elimina altre informazioni personali collegate all'utente
            connection.execute(text('DELETE FROM carte WHERE persona = :email'), {'email': email})
            connection.execute(text('DELETE FROM dativenditori WHERE persona = :email'), {'email': email})
            connection.execute(text('DELETE FROM indirizzo WHERE persona = :email'), {'email': email})

            #  Elimina i prodotti venduti dall'utente
            product_ids_result = connection.execute(
                text('SELECT id FROM prodotto WHERE venditore = :email'),
                {'email': email}
            )
            product_ids = [row[0] for row in product_ids_result]

            if product_ids:
                connection.execute(
                    text('DELETE FROM taglie WHERE id_scarpa = ANY(:product_ids)'),
                    {'product_ids': product_ids}
                )
                connection.execute(
                    text('DELETE FROM prodotto WHERE id = ANY(:product_ids)'),
                    {'product_ids': product_ids}
                )

            #  Infine, elimina l'utente dalla tabella persona
            connection.execute(text('DELETE FROM persona WHERE email = :email'), {'email': email})

            transaction.commit()
            flash(f'Utente {email} eliminato con successo!', 'success')

    except Exception as e:
        if 'transaction' in locals() and transaction.is_active:
            transaction.rollback()
        flash(f'Errore durante l\'eliminazione dell\'utente {email}: {e}', 'danger')

    return redirect(url_for('admin_users'))



@app.route('/admin/delete_order/<int:id>', methods=['POST'])
def delete_order(id):
    try:
        with engine.connect() as connection:
            transaction = connection.begin()

            # 1️Trova gli ID dei prodotti nell'ordine
            result = connection.execute(
                text('SELECT prodotto FROM prodottiinordine WHERE ordine = :id'),
                {'id': id}
            )
            product_ids = [row[0] for row in result]

            # 2️Elimina le recensioni associate ai prodotti dell'ordine
            if product_ids:
                connection.execute(
                    text('DELETE FROM recensioni WHERE prodotto = ANY(:product_ids)'),
                    {'product_ids': product_ids}
                )

            # 3️Elimina i prodotti associati all'ordine
            connection.execute(
                text('DELETE FROM prodottiinordine WHERE ordine = :id'),
                {'id': id}
            )

            # 4️Ora puoi eliminare l'ordine
            connection.execute(
                text('DELETE FROM ordini WHERE id = :id'),
                {'id': id}
            )

            transaction.commit()
            flash(f'Ordine {id} eliminato con successo!', 'success')
    except Exception as e:
        if 'transaction' in locals() and transaction.is_active:
            transaction.rollback()
        flash(f'Errore durante l\'eliminazione dell\'ordine {id}: {e}', 'danger')

    return redirect(url_for('admin_orders'))


@app.route('/admin/delete_shoe/<int:product_id>', methods=['POST'])
def delete_shoe(product_id):
    try:
        with engine.connect() as connection:
            transaction = connection.begin()

            # 1️⃣ Elimina le recensioni associate al prodotto
            connection.execute(
                text('DELETE FROM recensioni WHERE prodotto = :product_id'),
                {'product_id': product_id}
            )

            # 2️⃣ Verifica se ci sono ordini associati
            result = connection.execute(
                text('SELECT COUNT(*) FROM prodottiinordine WHERE prodotto = :product_id'),
                {'product_id': product_id}
            )
            orders_count = result.scalar()

            if orders_count > 0:
                # Se ci sono ordini, cancellali prima
                connection.execute(
                    text('DELETE FROM prodottiinordine WHERE prodotto = :product_id'),
                    {'product_id': product_id}
                )

                connection.execute(
                    text('DELETE FROM ordini WHERE id IN (SELECT ordine FROM prodottiinordine WHERE prodotto = :product_id)'),
                    {'product_id': product_id}
                )

            # 3️⃣ Elimina la scarpa dalla tabella taglie
            connection.execute(
                text('DELETE FROM taglie WHERE id_scarpa = :product_id'),
                {'product_id': product_id}
            )

            # 4️⃣ Elimina la scarpa dalla tabella prodotto
            connection.execute(
                text('DELETE FROM prodotto WHERE id = :product_id'),
                {'product_id': product_id}
            )

            transaction.commit()
            flash(f'Scarpa con ID {product_id} e relativi ordini eliminati con successo!', 'success')
    except Exception as e:
        if 'transaction' in locals() and transaction.is_active:
            transaction.rollback()
        flash(f'Errore durante l\'eliminazione della scarpa {product_id}: {e}', 'danger')

    return redirect(url_for('admin_shoes'))





if __name__ == '__main__':
    app.run(debug=True)