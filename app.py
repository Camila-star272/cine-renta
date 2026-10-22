from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    abort,
    jsonify,
)
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "cinerenta-clave-secreta-cambiar-en-produccion"
)

# ======================
# Configuración Login
# ======================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Inicia sesión para continuar"
login_manager.login_message_category = "warning"

# ======================
# Conexión a MongoDB
# ======================
mongo_uri = os.environ.get("MONGO_URI")
if not mongo_uri:
    if os.environ.get("RENDER"):
        raise RuntimeError("Configura MONGO_URI en Render.")
    mongo_uri = "mongodb://127.0.0.1:27017/"

cliente = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000)
base_datos = cliente["cinerenta"]

peliculas = base_datos["peliculas"]
usuarios = base_datos["usuarios"]
pedidos = base_datos["pedidos"]


# ======================
# Modelo de Usuario
# ======================
class Usuario(UserMixin):
    def __init__(self, usuario_data):
        self.id = str(usuario_data["_id"])
        self.nombre = usuario_data.get("nombre", "")
        self.email = usuario_data.get("email", "")
        self.rol = usuario_data.get("rol", "cliente")


@login_manager.user_loader
def load_user(user_id):
    try:
        data = usuarios.find_one({"_id": ObjectId(user_id)})
        if data:
            return Usuario(data)
    except Exception:
        return None
    return None


# ======================
# Decorador solo admin
# ======================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != "admin":
            flash("Solo el administrador puede realizar esta acción", "danger")
            return redirect(url_for("inicio"))
        return f(*args, **kwargs)

    return decorated_function


# ======================
# Funciones auxiliares
# ======================
def buscar_pelicula(id_str):
    try:
        pelicula = peliculas.find_one({"_id": ObjectId(id_str)})
        if not pelicula:
            abort(404, description="Esta película ya no existe")
        return pelicula
    except Exception:
        abort(404, description="La clave de la película no es válida")


def leer_formulario_pelicula(datos=None):
    if datos is None:
        datos = request.form

    campos = ("nombre", "genero", "estado", "precio", "imagen", "descripcion", "anio")
    for c in campos:
        if c not in datos or not str(datos.get(c, "")).strip():
            abort(400, description=f"Completa el campo: {c}")

    try:
        precio = float(datos.get("precio"))
        anio = int(datos.get("anio"))
    except ValueError:
        abort(400, description="Precio y año deben ser números válidos")

    estado = datos.get("estado").strip()
    if estado not in ["Disponible", "Alquilada"]:
        abort(400, description="Estado no válido")

    trailer = datos.get("trailer", "").strip()

    return {
        "nombre": datos.get("nombre").strip(),
        "genero": datos.get("genero").strip(),
        "estado": estado,
        "precio": precio,
        "imagen": datos.get("imagen").strip(),
        "descripcion": datos.get("descripcion").strip(),
        "anio": anio,
        "trailer": trailer,
    }


# ======================
# Rutas públicas
# ======================
@app.route("/")
def inicio():
    lista = list(peliculas.find().sort("nombre", 1))
    return render_template("index.html", peliculas=lista)


@app.route("/pelicula/<id>")
def detalle_pelicula(id):
    pelicula = buscar_pelicula(id)
    return render_template("detalle.html", pelicula=pelicula)


@app.route("/ayuda")
def ayuda():
    return render_template("ayuda.html", fecha=datetime.now().strftime("%d/%m/%Y"))


# ======================
# Autenticación
# ======================
@app.route("/registro", methods=["GET", "POST"])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for("inicio"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not nombre or not email or not password:
            flash("Completa todos los campos", "danger")
            return redirect(url_for("registro"))

        if usuarios.find_one({"email": email}):
            flash("Ese correo ya está registrado", "warning")
            return redirect(url_for("registro"))

        usuarios.insert_one(
            {
                "nombre": nombre,
                "email": email,
                "password": generate_password_hash(password),
                "rol": "cliente",
                "creado": datetime.utcnow(),
            }
        )
        flash("Cuenta creada. Ya puedes iniciar sesión", "success")
        return redirect(url_for("login"))

    return render_template("registro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("inicio"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        usuario = usuarios.find_one({"email": email})
        if usuario and check_password_hash(usuario["password"], password):
            login_user(Usuario(usuario))
            flash(f"Bienvenido, {usuario['nombre']}", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("inicio"))
        else:
            flash("Correo o contraseña incorrectos", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada", "info")
    return redirect(url_for("inicio"))


# ======================
# CRUD de películas (solo admin)
# ======================
@app.route("/agregar", methods=["GET", "POST"])
@login_required
@admin_required
def agregar():
    if request.method == "POST":
        datos = leer_formulario_pelicula()
        peliculas.insert_one(datos)
        flash("Película agregada correctamente", "success")
        return redirect(url_for("inicio"))
    return render_template("agregar.html")


@app.route("/editar/<id>", methods=["GET", "POST"])
@login_required
@admin_required
def editar(id):
    pelicula = buscar_pelicula(id)
    if request.method == "POST":
        datos = leer_formulario_pelicula()
        peliculas.update_one({"_id": pelicula["_id"]}, {"$set": datos})
        flash("Película actualizada", "success")
        return redirect(url_for("inicio"))
    return render_template("editar.html", pelicula=pelicula)


@app.route("/eliminar/<id>", methods=["POST"])
@login_required
@admin_required
def eliminar(id):
    pelicula = buscar_pelicula(id)
    peliculas.delete_one({"_id": pelicula["_id"]})
    flash("Película eliminada", "info")
    return redirect(url_for("inicio"))


# ======================
# Carrito
# ======================
@app.route("/carrito")
@login_required
def carrito():
    carrito_ids = session.get("carrito", [])
    items = []
    total = 0
    for pid in carrito_ids:
        try:
            p = peliculas.find_one({"_id": ObjectId(pid)})
            if p:
                items.append(p)
                total += p.get("precio", 0)
        except Exception:
            continue
    return render_template("carrito.html", items=items, total=total)


@app.route("/carrito/agregar/<id>")
@login_required
def carrito_agregar(id):
    buscar_pelicula(id)
    carrito = session.get("carrito", [])
    if id not in carrito:
        carrito.append(id)
        session["carrito"] = carrito
        flash("Película agregada al carrito", "success")
    else:
        flash("Ya está en el carrito", "info")
    return redirect(url_for("inicio"))


@app.route("/carrito/quitar/<id>")
@login_required
def carrito_quitar(id):
    carrito = session.get("carrito", [])
    if id in carrito:
        carrito.remove(id)
        session["carrito"] = carrito
        flash("Película quitada del carrito", "info")
    return redirect(url_for("carrito"))


@app.route("/carrito/vaciar", methods=["GET", "POST"])
@login_required
def carrito_vaciar():
    session.pop("carrito", None)
    flash("Carrito vaciado", "info")
    return redirect(url_for("carrito"))


# ======================
# Checkout (pago simulado)
# ======================
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    carrito_ids = session.get("carrito", [])
    if not carrito_ids:
        flash("El carrito está vacío", "warning")
        return redirect(url_for("carrito"))

    if request.method == "GET":
        items = []
        total = 0.0
        for pid in carrito_ids:
            try:
                p = peliculas.find_one({"_id": ObjectId(pid)})
                if p and p.get("estado") == "Disponible":
                    items.append(p)
                    total += float(p.get("precio", 0))
            except Exception:
                continue
        return render_template("checkout.html", items=items, total=total)

    # POST → procesar pago
    nombre_cliente = request.form.get("nombre_cliente", "").strip()
    email_cliente = request.form.get("email_cliente", "").strip()
    tarjeta = request.form.get("tarjeta", "").strip()

    if not nombre_cliente or not email_cliente or not tarjeta:
        flash("Completa todos los datos de pago", "danger")
        return redirect(url_for("checkout"))

    items = []
    total = 0.0
    for pid in carrito_ids:
        try:
            p = peliculas.find_one({"_id": ObjectId(pid)})
            if p and p.get("estado") == "Disponible":
                items.append(
                    {
                        "pelicula_id": str(p["_id"]),
                        "nombre": p.get("nombre", ""),
                        "precio": float(p.get("precio", 0)),
                    }
                )
                total += float(p.get("precio", 0))
                peliculas.update_one(
                    {"_id": p["_id"]}, {"$set": {"estado": "Alquilada"}}
                )
        except Exception:
            continue

    if not items:
        flash("No hay películas disponibles en el carrito", "warning")
        return redirect(url_for("carrito"))

    pedido = {
        "usuario_id": current_user.id,
        "usuario_nombre": current_user.nombre,
        "cliente_nombre": nombre_cliente,
        "cliente_email": email_cliente,
        "tarjeta_ultimos4": tarjeta[-4:] if len(tarjeta) >= 4 else tarjeta,
        "items": items,
        "total": total,
        "estado": "Completado",
        "fecha": datetime.utcnow(),
    }
    pedidos.insert_one(pedido)
    session.pop("carrito", None)

    flash(
        f"¡Pago realizado con éxito! Se enviará la película al correo {email_cliente}",
        "success",
    )
    return redirect(url_for("mis_pedidos"))


@app.route("/mis-pedidos")
@login_required
def mis_pedidos():
    try:
        lista = list(pedidos.find({"usuario_id": current_user.id}).sort("fecha", -1))
    except Exception:
        lista = []
    return render_template("pedidos.html", pedidos=lista)


# ======================
# API
# ======================
@app.route("/api/peliculas", methods=["GET", "POST"])
def api_peliculas():
    if request.method == "GET":
        lista = peliculas.find().sort("nombre", 1)
        resultado = []
        for p in lista:
            resultado.append(
                {
                    "id": str(p["_id"]),
                    "nombre": p.get("nombre"),
                    "genero": p.get("genero"),
                    "estado": p.get("estado"),
                    "precio": p.get("precio"),
                    "imagen": p.get("imagen"),
                    "anio": p.get("anio"),
                    "trailer": p.get("trailer", ""),
                }
            )
        return jsonify(resultado)

    # POST - ESTO ES LO QUE TE FALTABA
    datos = request.get_json()
    nuevo = {
        "nombre": datos.get("nombre"),
        "genero": datos.get("categoria", "Drama"),
        "estado": datos.get("estado", "Disponible"),
        "precio": 65.0,
        "imagen": "https://via.placeholder.com/300",
    }
    res = peliculas.insert_one(nuevo)
    return jsonify({"id": str(res.inserted_id), "nombre": nuevo["nombre"]}), 201


@app.route("/api/peliculas/<id>", methods=["GET", "PUT", "DELETE"])
def api_pelicula_detalle(id):
    from bson import ObjectId

    oid = ObjectId(id)
    if request.method == "GET":
        p = peliculas.find_one({"_id": oid})
        return jsonify({"id": str(p["_id"]), "nombre": p["nombre"]})
    if request.method == "PUT":
        datos = request.get_json()
        if "categoria" in datos:
            datos["genero"] = datos.pop("categoria")
        peliculas.update_one({"_id": oid}, {"$set": datos})
        return jsonify({"ok": True})
    if request.method == "DELETE":
        peliculas.delete_one({"_id": oid})
        return jsonify({"ok": True, "borrado": id})


# ======================
# Manejo de errores
# ======================
@app.errorhandler(PyMongoError)
def error_mongo(error):
    mensaje = "No fue posible conectar con la base de datos."
    if request.path.startswith("/api/"):
        return jsonify({"error": mensaje}), 503
    return render_template("error.html", mensaje=mensaje), 503


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(405)
def error_peticion(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": getattr(error, "description", str(error))}), error.code
    return (
        render_template(
            "error.html", mensaje=getattr(error, "description", str(error))
        ),
        error.code,
    )


# ======================
# Arranque
# ======================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
