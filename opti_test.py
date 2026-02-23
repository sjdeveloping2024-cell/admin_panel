from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from flask_socketio import SocketIO
from datetime import datetime, time as dt_time
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
import io, csv
import threading, time

# -----------------------------
# App Config
# -----------------------------
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
app.secret_key = "blackpower"

# -----------------------------
# MySQL Connection
# -----------------------------
connection = pymysql.connect(
    host="localhost",
    user="root",
    password="saquilon",
    database="opti_test",
    cursorclass=pymysql.cursors.DictCursor
)
cursor = connection.cursor()

# -----------------------------
# Admin Credentials
# -----------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = generate_password_hash("admin123")

# -----------------------------
# Attendance Settings
# -----------------------------
SCAN_COOLDOWN_SECONDS = 1
SHIFT_START = dt_time(8, 0, 0)
SHIFT_END = dt_time(17, 0, 0)
last_scan_time = {}

# -----------------------------
# Arduino Setup
# -----------------------------
arduino = None
arduino_connected = False
try:
    import serial
    arduino = serial.Serial('COM3', 9600, timeout=1)
    time.sleep(2)
    arduino_connected = True
    print("Arduino connected successfully.")
except Exception as e:
    print(f"Arduino not connected: {e}")

def arduino_beep(status):
    if not arduino_connected:
        return
    try:
        arduino.write(f"BEEP_{status}\n".encode())
    except:
        pass

# Arduino background thread
def read_from_arduino():
    if not arduino_connected: return
    while True:
        try:
            if arduino.in_waiting > 0:
                data = arduino.readline().decode().strip()
                if data:
                    socketio.emit("arduino_data", {"data": data})
        except:
            pass
        time.sleep(0.1)

if arduino_connected:
    thread = threading.Thread(target=read_from_arduino)
    thread.daemon = True
    thread.start()

# -----------------------------
# Admin Routes
# -----------------------------
@app.route("/", methods=["GET"])
def landing_page():
    return render_template("admin_login.html", error=None)

@app.route("/log_in_admin", methods=["POST"])
def log_in_admin():
    admin = request.form.get('username')
    password = request.form.get('password')
    if admin == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
        session["admin"] = admin
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html", error="Invalid credentials")

@app.route("/admin_dashboard")
def admin_dashboard():
    if "admin" not in session:
        return redirect(url_for("landing_page"))

    today = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT opti.name, opti_rec.time_in, opti_rec.time_out, 
               opti_rec.duration, opti_rec.salary,
               opti_rec.late_minutes, opti_rec.undertime_minutes
        FROM opti_rec
        JOIN opti ON opti_rec.id_employee = opti.id_employee
        WHERE DATE(opti_rec.time_in)=%s
        ORDER BY opti_rec.time_in DESC
    """, (today,))
    records = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS total FROM opti")
    total_employees = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS present FROM opti_rec WHERE DATE(time_in)=%s", (today,))
    present_today = cursor.fetchone()["present"]

    cursor.execute("SELECT IFNULL(SUM(salary),0) AS total_salary FROM opti_rec WHERE DATE(time_in)=%s", (today,))
    total_salary = cursor.fetchone()["total_salary"]

    cursor.execute("SELECT * FROM opti ORDER BY id_employee ASC")
    employees = cursor.fetchall()

    return render_template(
        "admin_dashboard.html",
        admin_name=session.get("admin","Admin"),
        total_employees=total_employees,
        present_today=present_today,
        total_salary=total_salary,
        records=records,
        employees=employees
    )

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("landing_page"))

# -----------------------------
# Employee Management Routes
# -----------------------------
@app.route("/add_employee", methods=["POST"])
def add_employee():
    data = request.form
    name = data.get('name_inp')
    age = data.get('age_inp')
    sex = data.get('sex_inp')
    email = data.get('email_inp')
    number = data.get("num_inp")
    rfid = data.get('rfid_inp')

    cursor.execute("SELECT id_employee FROM opti ORDER BY id_employee ASC")
    existing_ids = [row['id_employee'] for row in cursor.fetchall()]
    next_id = 1
    for eid in existing_ids:
        if eid == next_id: next_id += 1
        else: break

    cursor.execute(
        "INSERT INTO opti (id_employee, name, age, sex, email, number, rfid) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (next_id, name, age, sex, email, number, rfid)
    )
    connection.commit()
    cursor.execute("SELECT * FROM opti WHERE id_employee=%s", (next_id,))
    new_emp = cursor.fetchone()
    return jsonify(new_emp)

@app.route("/drop_employee", methods=["POST"])
def drop_employee():
    emp_id = int(request.form.get("employ_id"))
    cursor.execute("DELETE FROM opti WHERE id_employee=%s", (emp_id,))
    connection.commit()
    cursor.execute("SELECT id_employee FROM opti ORDER BY id_employee ASC")
    employees = cursor.fetchall()
    for index, emp in enumerate(employees, start=1):
        if emp['id_employee'] != index:
            cursor.execute("UPDATE opti SET id_employee=%s WHERE id_employee=%s", (index, emp['id_employee']))
    connection.commit()
    return jsonify({"status": "success"})

# -----------------------------
# Export to Excel
# -----------------------------
@app.route("/export_excel")
def export_excel():
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT opti.name, opti_rec.time_in, opti_rec.time_out, opti_rec.duration, opti_rec.salary
        FROM opti_rec
        JOIN opti ON opti_rec.id_employee = opti.id_employee
        WHERE DATE(opti_rec.time_in)=%s
        ORDER BY opti_rec.time_in DESC
    """, (today,))
    records = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Time In", "Time Out", "Duration (min)", "Salary"])
    for r in records:
        writer.writerow([
            r["name"],
            r["time_in"].strftime("%H:%M") if r["time_in"] else "",
            r["time_out"].strftime("%H:%M") if r["time_out"] else "",
            r.get("duration",""),
            r.get("salary","")
        ])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"attendance_{today}.csv"
    )

# -----------------------------
# API Routes
# -----------------------------
@app.route("/api/add_employee", methods=["POST"])
def api_add_employee():
    data = request.json
    name = data.get("name")
    age = data.get("age")
    sex = data.get("sex")
    email = data.get("email")
    number = data.get("number")
    rfid = data.get("rfid")

    cursor.execute("SELECT id_employee FROM opti ORDER BY id_employee ASC")
    existing_ids = [row['id_employee'] for row in cursor.fetchall()]
    next_id = 1
    for eid in existing_ids:
        if eid == next_id: next_id += 1
        else: break

    cursor.execute(
        "INSERT INTO opti (id_employee, name, age, sex, email, number, rfid) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (next_id, name, age, sex, email, number, rfid)
    )
    connection.commit()
    cursor.execute("SELECT * FROM opti WHERE id_employee=%s", (next_id,))
    new_emp = cursor.fetchone()
    return jsonify({"status": "success", "employee": new_emp})

@app.route("/api/drop_employee", methods=["POST"])
def api_drop_employee():
    data = request.json
    emp_id = data.get("employ_id")
    cursor.execute("DELETE FROM opti WHERE id_employee=%s", (emp_id,))
    connection.commit()
    cursor.execute("SELECT id_employee FROM opti ORDER BY id_employee ASC")
    employees = cursor.fetchall()
    for index, emp in enumerate(employees, start=1):
        if emp['id_employee'] != index:
            cursor.execute("UPDATE opti SET id_employee=%s WHERE id_employee=%s", (index, emp['id_employee']))
    connection.commit()
    return jsonify({"status": "success"})

@app.route("/api/export_today")
def api_export_today():
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT opti.name, opti_rec.time_in, opti_rec.time_out, opti_rec.duration, opti_rec.salary
        FROM opti_rec
        JOIN opti ON opti_rec.id_employee = opti.id_employee
        WHERE DATE(opti_rec.time_in)=%s
        ORDER BY opti_rec.time_in DESC
    """, (today,))
    records = cursor.fetchall()
    return jsonify({"records": records})

# -----------------------------
# Scan API
# -----------------------------
@app.route("/api/scan", methods=["POST"])
def api_scan():
    uid = request.json.get("uid")
    now = datetime.now()

    # cooldown
    if uid in last_scan_time:
        if (now - last_scan_time[uid]).total_seconds() < SCAN_COOLDOWN_SECONDS:
            arduino_beep("ERROR")
            return jsonify({"status": "cooldown"})
    last_scan_time[uid] = now

    cursor.execute("SELECT * FROM opti WHERE rfid=%s", (uid,))
    employee = cursor.fetchone()
    if not employee:
        arduino_beep("ERROR")
        return jsonify({"status": "not_found"})

    today = now.strftime("%Y-%m-%d")
    cursor.execute("SELECT * FROM opti_rec WHERE id_employee=%s AND DATE(time_in)=%s",
                   (employee["id_employee"], today))
    record = cursor.fetchone()

    # TIME IN
    if not record:
        late_minutes = 0
        if now.time() > SHIFT_START:
            late_minutes = int(
                (datetime.combine(now.date(), now.time()) -
                 datetime.combine(now.date(), SHIFT_START)
                 ).total_seconds() // 60
            )
        cursor.execute("""
            INSERT INTO opti_rec (id_employee, time_in, late_minutes)
            VALUES (%s, %s, %s)
        """, (employee["id_employee"], now, late_minutes))
        connection.commit()
        arduino_beep("SUCCESS")
        socketio.emit("attendance_update", {"name": employee["name"], "status": "time_in", "late_minutes": late_minutes})
        return jsonify({"status": "time_in", "late_minutes": late_minutes})

    # TIME OUT
    elif record and not record["time_out"]:
        time_in_db = record["time_in"]
        duration_min = int((now - time_in_db).total_seconds() // 60)
        undertime_minutes = 0
        if now.time() < SHIFT_END:
            undertime_minutes = int(
                (datetime.combine(now.date(), SHIFT_END) -
                 datetime.combine(now.date(), now.time())
                 ).total_seconds() // 60
            )
        salary = duration_min * 5
        cursor.execute("""
            UPDATE opti_rec
            SET time_out=%s, duration=%s, salary=%s, undertime_minutes=%s
            WHERE id=%s
        """, (now, duration_min, salary, undertime_minutes, record["id"]))
        connection.commit()
        arduino_beep("SUCCESS")
        socketio.emit("attendance_update", {
            "name": employee["name"],
            "status": "time_out",
            "duration": duration_min,
            "salary": salary,
            "undertime_minutes": undertime_minutes
        })
        return jsonify({"status": "time_out", "duration": duration_min, "salary": salary, "undertime_minutes": undertime_minutes})

    else:
        arduino_beep("ERROR")
        return jsonify({"status": "already_done"})

# -----------------------------
# Monthly Payroll
# -----------------------------
@app.route("/monthly_payroll")
def monthly_payroll():
    if "admin" not in session:
        return redirect(url_for("landing_page"))

    today = datetime.now()
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    month_end = today.strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT o.name, 
               SUM(r.duration) AS total_minutes, 
               SUM(r.salary) AS total_salary,
               SUM(r.late_minutes) AS total_late,
               SUM(r.undertime_minutes) AS total_undertime
        FROM opti_rec r
        JOIN opti o ON r.id_employee = o.id_employee
        WHERE DATE(r.time_in) BETWEEN %s AND %s
        GROUP BY o.id_employee
        ORDER BY o.id_employee ASC
    """, (month_start, month_end))

    payrolls = cursor.fetchall()
    return render_template("monthly_payroll.html", payrolls=payrolls, month=today.strftime("%B %Y"))

@app.route("/api/monthly_payroll")
def api_monthly_payroll():
    today = datetime.now()
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    month_end = today.strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT o.name, 
               SUM(r.duration) AS total_minutes, 
               SUM(r.salary) AS total_salary,
               SUM(r.late_minutes) AS total_late,
               SUM(r.undertime_minutes) AS total_undertime
        FROM opti_rec r
        JOIN opti o ON r.id_employee = o.id_employee
        WHERE DATE(r.time_in) BETWEEN %s AND %s
        GROUP BY o.id_employee
        ORDER BY o.id_employee ASC
    """, (month_start, month_end))

    payrolls = cursor.fetchall()
    return jsonify({"payrolls": payrolls})

# -----------------------------
# Run App
# -----------------------------
if __name__ == "__main__":
    socketio.run(app, port=5000, debug=True)