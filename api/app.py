from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import pyodbc
import os
import logging


# Configurăm logging-ul aplicației.
# Toate mesajele de log se vor salva în fișierul patient_api.log si in consola.
# filemode="a" înseamnă append, adică NU suprascrie logul vechi.
# --------------------------------------------------
# CONFIGURARE LOGGING
# --------------------------------------------------
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "patient_api.log")

# Dacă folderul logs nu există, îl creăm automat.
os.makedirs(LOG_DIR, exist_ok=True)

# Logger-ul este obiectul principal care primește mesajele de log.
logger = logging.getLogger("patient_api")

# Spunem că vrem să logăm de la nivelul INFO în sus.
logger.setLevel(logging.INFO)

# Evităm să adăugăm handler-ele de mai multe ori,
# în caz că fișierul este reîncărcat.
if not logger.handlers:

    # Formatter-ul stabilește cum arată fiecare linie din log.
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    # Handler pentru fișier.
    # Aici logurile se salvează în patient_api.log.
    file_handler = logging.FileHandler(LOG_FILE, mode="a")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # Handler pentru consolă.
    # Aici logurile apar în docker logs api.
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Atașăm ambele handler-e la logger.
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# Această clasă definește cum răspunde API-ul nostru la request-uri HTTP.
# BaseHTTPRequestHandler este o clasă standard din Python pentru servere HTTP simple.
class PatientHandler(BaseHTTPRequestHandler):

    # Această metodă se execută automat când cineva face un GET request.
    # Exemplu: curl http://localhost:8000/patient/1
    def do_GET(self):
        logger.info("Received GET request: %s", self.path)

        try:
            # Împărțim URL-ul după caracterul "/".
            # Exemplu: "/patient/1" devine ["", "patient", "1"]
            parts = self.path.split("/")

            # Verificăm dacă URL-ul are forma corectă:
            # /patient/1
            if len(parts) != 3 or parts[1] != "patient":
                logger.warning("Invalid endpoint called: %s", self.path)

                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
                return

            # Încercăm să extragem ID-ul pacientului din URL.
            # parts[2] este "1" în exemplul /patient/1.
            try:
                patient_id = int(parts[2])
                logger.info("Extracted patientId from URL: %s", patient_id)

            except ValueError:
                # Dacă cineva trimite /patient/abc,
                # nu putem transforma "abc" în număr.
                logger.error("Invalid patientId format: %s", parts[2])

                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid patientId")
                return

            # Inițializăm conexiunea cu None.
            # Facem asta ca să putem verifica în finally dacă a fost creată.
            connection = None

            try:
                # Încercăm să ne conectăm la SQL Server.
                logger.info("Trying to connect to SQL Server...")

                connection = pyodbc.connect(
                    "DRIVER={ODBC Driver 18 for SQL Server};"
                    "SERVER=patient-db-service,1433;"
                    "DATABASE=PatientMonitoring;"
                    "UID=sa;"
                    "PWD=Password123!;"
                    "TrustServerCertificate=yes;"
                )

                logger.info("Database connection successful.")

                # Cursorul este obiectul prin care trimitem query-uri SQL către baza de date.
                cursor = connection.cursor()

                # Executăm query-ul SQL.
                # Semnul ? este placeholder pentru patient_id.
                # Asta ajută să evităm SQL injection.
                cursor.execute(
                    """
                    SELECT patientId, name, room, heartRate, oxygen, alarm
                    FROM Patients
                    WHERE patientId = ?
                    """,
                    patient_id
                )

                # Luăm primul rând returnat de baza de date.
                row = cursor.fetchone()

                # Dacă nu există pacient cu acel ID, returnăm 404.
                if row is None:
                    logger.warning("No patient found with patientId=%s", patient_id)

                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Patient not found")
                    return

                # Construim un dicționar Python cu datele pacientului.
                # Acesta va fi transformat apoi în JSON.
                patient = {
                    "patientId": row.patientId,
                    "name": row.name,
                    "room": row.room,
                    "heartRate": row.heartRate,
                    "oxygen": row.oxygen,
                    "alarm": bool(row.alarm)
                }

                # Transformăm dicționarul Python în JSON.
                # encode("utf-8") îl transformă în bytes, pentru că wfile.write cere bytes.
                response = json.dumps(patient).encode("utf-8")

                # Trimitem răspuns HTTP 200 OK.
                self.send_response(200)

                # Spunem clientului că răspunsul este JSON.
                self.send_header("Content-Type", "application/json")

                # Încheiem partea de headers.
                self.end_headers()

                # Scriem efectiv JSON-ul în răspuns.
                self.wfile.write(response)

                logger.info("Successfully returned patient data for patientId=%s", patient_id)

            except pyodbc.Error as db_error:
                # Aici ajungem dacă apare o problemă cu baza de date:
                # conexiune eșuată, query greșit, tabel lipsă etc.
                logger.exception("Database error occurred: %s", db_error)

                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Database error")

            finally:
                # finally se execută indiferent dacă a mers sau a crăpat codul.
                # Îl folosim ca să închidem conexiunea la baza de date.
                if connection is not None:
                    connection.close()
                    logger.info("Database connection closed.")

        except Exception as error:
            # Acesta este catch-ul general.
            # Prinde orice eroare neașteptată care nu a fost prinsă mai sus.
            logger.exception("Unexpected error occurred: %s", error)

            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal server error")


# Creăm serverul HTTP.
# 0.0.0.0 înseamnă că serverul ascultă pe toate interfețele din container.
# 8000 este portul pe care rulează API-ul în container.
server = HTTPServer(("0.0.0.0", 8000), PatientHandler)

# Logăm și afișăm că serverul a pornit.
logger.info("Patient API started on port 8000")
print("Patient API started on http://localhost:8000", flush=True)

# Pornim serverul și îl lăsăm să ruleze continuu.
server.serve_forever()