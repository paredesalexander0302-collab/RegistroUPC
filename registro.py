import streamlit as st
import re
from datetime import datetime
import pandas as pd
import gspread
from fpdf import FPDF
import tempfile
import os
from google.oauth2.service_account import Credentials
import json


try:
    # Usamos scopes ampliados para permitir subir archivos a Drive
    SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive']
    creds_drive = Credentials.from_service_account_file('credenciales.json', scopes=SCOPES_DRIVE)
    drive_service = build('drive', 'v3', credentials=creds_drive)
except Exception as e:
    # Si falla silenciosamente, Streamlit mostrará el error en la interfaz más adelante
    drive_service = None

def subir_pdf_a_drive(pdf_bytes, nombre_archivo, folder_id):
    """Sube un archivo PDF directamente a una carpeta específica de Google Drive."""
    if not drive_service:
        st.error("🚨 Error crítico: El servicio de Google Drive no se inicializó correctamente.")
        return None
    try:
        file_metadata = {
            'name': nombre_archivo,
            'parents': [folder_id]
        }
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf', resumable=True)
        archivo = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return archivo.get('id')
    except Exception as e:
        # AQUÍ ESTÁ LA MAGIA: Esto mostrará el error exacto en tu pantalla
        st.error(f"⚠️ Google Drive rechazó el archivo. Motivo exacto: {e}")
        return None
# Configuración básica de la página
st.set_page_config(page_title="Sistema de Registro UPC", layout="wide")

# --- CONEXIÓN A GOOGLE SHEETS ---
# Usamos st.cache_resource para no abrir una conexión nueva con cada clic
@st.cache_resource
def conectar_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    try:
        # 1. Leemos el texto crudo del secreto de Streamlit
        credenciales_texto = st.secrets["GOOGLE_CREDENTIALS_JSON"]
        
        # 2. EL TRUCO ESTÁ AQUÍ: strict=False permite leer los saltos de línea ocultos sin romperse
        credenciales_info = json.loads(credenciales_texto, strict=False)
        
        # 3. Nos conectamos usando la información del secreto
        credenciales = Credentials.from_service_account_info(
            credenciales_info,
            scopes=scopes
        )
        cliente = gspread.authorize(credenciales)
        
        # ID real de tu Google Sheet
        SPREADSHEET_ID = "1QVluCNoVihqku69oKiXhbks3IZypaJRVaomSW0hzkOk"
        
        hoja_calculo = cliente.open_by_key(SPREADSHEET_ID)
        return hoja_calculo
        
    except Exception as e:
        st.error(f"⚠️ Error de conexión a la base de datos: {e}")
        return None
    
def validar_cedula(cedula):
    return bool(re.fullmatch(r'\d{10}', cedula))

# --- FUNCIONES DE BASE DE DATOS (GOOGLE SHEETS) ---
def buscar_historial_persona(cedula, doc):
    if not doc: return []
    try:
        ws = doc.worksheet("Detenidos")
        datos = ws.get_all_records()
        df = pd.DataFrame(datos)
        if not df.empty:
            # LIMPIEZA: Elimina cualquier espacio oculto al inicio o final de los nombres de las columnas
            df.columns = df.columns.str.strip()
            
            # Buscar la columna exacta de la cédula
            col_cedula = 'Cédula' if 'Cédula' in df.columns else 'Cedula'
            
            if col_cedula in df.columns:
                df[col_cedula] = df[col_cedula].astype(str).str.replace("'", "").str.strip()
                historial = df[df[col_cedula] == str(cedula).strip()]
                return historial.to_dict('records')
        return []
    except Exception as e:
        return []

def guardar_registro_persona(datos, doc):
    if not doc: return False
    try:
        ws = doc.worksheet("Detenidos")
        # Añadir fila al final de la hoja
        ws.append_row(datos)
        return True
    except:
        return False

def buscar_vehiculo(placa, doc):
    if not doc: return None
    try:
        ws = doc.worksheet("Vehiculos")
        datos = ws.get_all_records()
        df = pd.DataFrame(datos)
        if not df.empty:
            df['Placa'] = df['Placa'].astype(str)
            # Buscar si existe y si su estado es "Ingresado"
            vehiculo = df[(df['Placa'] == str(placa)) & (df['Estado'] == 'Ingresado')]
            if not vehiculo.empty:
                return vehiculo.iloc[-1].to_dict() # Retorna el registro más reciente
        return None
    except:
        return None

def guardar_ingreso_vehiculo(datos, doc):
    if not doc: return False
    try:
        ws = doc.worksheet("Vehiculos")
        ws.append_row(datos)
        return True
    except:
        return False

def actualizar_salida_vehiculo(placa, datos_salida, doc):
    if not doc: return False
    try:
        ws = doc.worksheet("Vehiculos")
        celda_placa = ws.find(placa)
        if celda_placa:
            fila = celda_placa.row
            # Actualizamos desde la columna K (Estado) hasta la P (Hora Salida)
            rango = f"K{fila}:P{fila}"
            
            # SOLUCIÓN AL WARNING: Usamos argumentos nombrados explícitos
            ws.update(values=[["Retirado"] + datos_salida], range_name=rango)
            
            return True
        return False
    except Exception as e:
        st.error(f"Error en actualización: {e}")
        return False

# Intentamos conectar a la base de datos al iniciar
db_doc = conectar_sheets()
# --- GENERADOR DE PDF ---
def limpiar_texto(texto):
    """Limpia caracteres especiales para evitar errores en FPDF."""
    return str(texto).encode('latin-1', 'replace').decode('latin-1')

class PDF(FPDF):
    def header(self):
        # Utiliza directamente tu archivo logo_policia.png
        if os.path.exists("logo_policia.png"):
            self.image("logo_policia.png", 10, 8, 25)
        
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, limpiar_texto('POLICÍA NACIONAL DEL ECUADOR'), 0, 1, 'C')
        self.set_font('Arial', 'I', 10)
        self.cell(0, 10, limpiar_texto('SISTEMA DE REGISTRO UPC - DISTRITO SAN MIGUEL'), 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

def generar_pdf_vehiculo(datos, foto_bytes):
    pdf = PDF()
    pdf.add_page()
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, limpiar_texto('PARTE DE INGRESO VEHICULAR'), 0, 1, 'C')
    pdf.ln(5)
    
   # Imprimir los datos en formato lista
    for clave, valor in datos.items():
        # 1. Guardamos la altura actual de la fila
        y_actual = pdf.get_y()
        
        # 2. Forzamos el título (Clave) a empezar en el margen izquierdo (X=10)
        pdf.set_font('Arial', 'B', 11)
        pdf.set_xy(10, y_actual)
        pdf.cell(60, 8, limpiar_texto(f"{clave}:"), 0, 0)
        
        # 3. Forzamos el contenido (Valor) a empezar 60mm a la derecha (X=70)
        pdf.set_font('Arial', '', 11)
        pdf.set_xy(70, y_actual)
        pdf.multi_cell(130, 8, limpiar_texto(str(valor)))
    
    # Procesar e incrustar la foto
    if foto_bytes:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(foto_bytes.getvalue())
            tmp_path = tmp.name
        
        pdf.ln(10)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 10, limpiar_texto('REGISTRO FOTOGRÁFICO:'), 0, 1, 'L')
        # Centrar la imagen
        pdf.image(tmp_path, x=60, w=90)
        
        # Eliminar el archivo temporal por seguridad
        os.unlink(tmp_path)
        
    resultado = pdf.output(dest='S')
    return resultado.encode('latin-1') if isinstance(resultado, str) else bytes(resultado)
def generar_pdf_detenido(datos, foto_bytes):
    pdf = PDF()
    pdf.add_page()
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, limpiar_texto('PARTE DE INGRESO DE DETENIDO'), 0, 1, 'C')
    pdf.ln(5)
    
    for clave, valor in datos.items():
        # 1. Guardamos la altura actual de la fila
        y_actual = pdf.get_y()
        
        # 2. Forzamos el título (Clave) a empezar en el margen izquierdo (X=10)
        pdf.set_font('Arial', 'B', 11)
        pdf.set_xy(10, y_actual)
        pdf.cell(60, 8, limpiar_texto(f"{clave}:"), 0, 0)
        
        # 3. Forzamos el contenido (Valor) a empezar 60mm a la derecha (X=70)
        pdf.set_font('Arial', '', 11)
        pdf.set_xy(70, y_actual)
        pdf.multi_cell(130, 8, limpiar_texto(str(valor)))
    
    if foto_bytes:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(foto_bytes.getvalue())
            tmp_path = tmp.name
        
        pdf.ln(10)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 10, limpiar_texto('REGISTRO FOTOGRÁFICO:'), 0, 1, 'L')
        pdf.image(tmp_path, x=60, w=90)
        os.unlink(tmp_path)
        
    resultado = pdf.output(dest='S')
    return resultado.encode('latin-1') if isinstance(resultado, str) else bytes(resultado)
def generar_pdf_salida_vehiculo(datos):
    pdf = PDF()
    pdf.add_page()
    
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, limpiar_texto('PARTE DE SALIDA / RETIRO VEHICULAR'), 0, 1, 'C')
    pdf.ln(5)
    
    for clave, valor in datos.items():
        # 1. Guardamos la altura actual de la fila
        y_actual = pdf.get_y()
        
        # 2. Forzamos el título (Clave) a empezar en el margen izquierdo (X=10)
        pdf.set_font('Arial', 'B', 11)
        pdf.set_xy(10, y_actual)
        pdf.cell(60, 8, limpiar_texto(f"{clave}:"), 0, 0)
        
        # 3. Forzamos el contenido (Valor) a empezar 60mm a la derecha (X=70)
        pdf.set_font('Arial', '', 11)
        pdf.set_xy(70, y_actual)
        pdf.multi_cell(130, 8, limpiar_texto(str(valor)))
        
    resultado = pdf.output(dest='S')
    return resultado.encode('latin-1') if isinstance(resultado, str) else bytes(resultado)
# Inicializar variables de sesión
if 'turno_activo' not in st.session_state:
    st.session_state['turno_activo'] = False
if 'servidor_nombre' not in st.session_state:
    st.session_state['servidor_nombre'] = ""
if 'servidor_cedula' not in st.session_state:
    st.session_state['servidor_cedula'] = ""
if 'upc_actual' not in st.session_state:
    st.session_state['upc_actual'] = ""
if 'cedula_busqueda' not in st.session_state:
    st.session_state['cedula_busqueda'] = ""
if 'placa_busqueda' not in st.session_state:
    st.session_state['placa_busqueda'] = ""

st.title("Sistema de Gestión y Registro - UPC")

# --- INTERFAZ DEL TURNO ---
if not st.session_state['turno_activo']:
    st.header("1. Identificación del Servidor Policial en Guardia")
    with st.form("form_servidor"):
        lista_upcs = [
            "UPC San Miguel", "UPC Chimbo", "UPC San Pablo", 
            "UPC Balsapamba", "UPC Telimbela", "UPC Santiago", "UPC Magdalena"
        ]
        upc_seleccionado = st.selectbox("Unidad de Policía Comunitaria (UPC)", lista_upcs)
        nombre_servidor = st.text_input("Grado, Nombres y Apellidos*")
        cedula_servidor = st.text_input("Número de Cédula*", max_chars=10)
        
        if st.form_submit_button("Iniciar Turno"):
            if nombre_servidor and validar_cedula(cedula_servidor):
                st.session_state['upc_actual'] = upc_seleccionado
                st.session_state['servidor_nombre'] = nombre_servidor.strip().upper()
                st.session_state['servidor_cedula'] = cedula_servidor
                st.session_state['turno_activo'] = True
                st.rerun()
            else:
                st.error("⚠️ Ingrese datos válidos.")
else:
    st.success(f"👮‍♂️ **Turno:** {st.session_state['servidor_nombre']} | 📍 **{st.session_state['upc_actual']}**")
    if st.button("Finalizar Turno"):
        st.session_state['turno_activo'] = False
        st.rerun()

    st.divider()
    # --- PESTAÑA DETENIDOS ---
    tab_detenidos, tab_vehiculos = st.tabs(["👤 Personas Detenidas", "🚗 Vehículos"])

    # ==========================================
    # --- PESTAÑA DETENIDOS ---
    # ==========================================
    with tab_detenidos:
        # Variables de memoria para el PDF y la foto
        if 'foto_key' not in st.session_state: st.session_state['foto_key'] = 0
        if 'pdf_detenido' not in st.session_state: st.session_state['pdf_detenido'] = None
        if 'pdf_detenido_name' not in st.session_state: st.session_state['pdf_detenido_name'] = ""

        def limpiar_formulario_detenido():
            for key in ['det_ap_p', 'det_ap_m', 'det_nom1', 'det_nom2', 'cedula_busqueda', 'det_prof']:
                st.session_state[key] = ""
            st.session_state['foto_key'] += 1

        # --- BOTÓN DE DESCARGA (FUERA DEL FORMULARIO) ---
        if st.session_state['pdf_detenido']:
            st.success("✅ Registro guardado en la matriz exitosamente.")
            st.download_button(
                label="📄 Descargar Parte de Detenido (PDF)",
                data=st.session_state['pdf_detenido'],
                file_name=st.session_state['pdf_detenido_name'],
                mime="application/pdf",
                type="primary"
            )
            if st.button("Finalizar y limpiar panel (Detenidos)"):
                st.session_state['pdf_detenido'] = None
                st.rerun()
            st.divider()

        st.subheader("🔍 Verificación de Historial")
        col_b1, col_b2 = st.columns([3, 1])
        with col_b1: 
            cedula_buscar = st.text_input("Cédula a verificar", value=st.session_state.get('cedula_busqueda', '')).strip()
        with col_b2: 
            st.write("")
            st.write("")
            btn_verificar = st.button("Verificar Historial Detenido", use_container_width=True)

        if btn_verificar:
            if validar_cedula(cedula_buscar):
                st.session_state['cedula_busqueda'] = cedula_buscar
                historial = buscar_historial_persona(cedula_buscar, db_doc)
                
                if historial:
                    st.error(f"🚨 Se encontraron {len(historial)} registro(s).")
                    ultimo = historial[-1] 
                    st.session_state['det_ap_p'] = str(ultimo.get('Apellido Paterno', ''))
                    st.session_state['det_ap_m'] = str(ultimo.get('Apellido Materno', ''))
                    st.session_state['det_nom1'] = str(ultimo.get('Primer Nombre', ''))
                    st.session_state['det_nom2'] = str(ultimo.get('Segundo Nombre', ''))
                    st.session_state['det_prof'] = str(ultimo.get('Profesión', ''))

                    for idx, reg in enumerate(historial):
                        fecha_reg = reg.get('Fecha Ingreso', 'S/F')
                        upc_reg = reg.get('UPC', 'S/U')
                        with st.expander(f"Ficha #{idx+1} - {fecha_reg} | {upc_reg}"):
                            motivo_texto = reg.get('Razón Detención', 'No especificado')
                            st.write(f"**Motivo:** {motivo_texto}")
                            st.write(f"**Registrado por:** {reg.get('Nombre Servidor', 'Desconocido')}")
                else:
                    st.success("✅ Sin registros previos.")
                    limpiar_formulario_detenido()
                    st.session_state['cedula_busqueda'] = cedula_buscar 

        with st.form("form_detenido", clear_on_submit=False):
            st.markdown("**Registro de Nuevo Detenido**")
            
            c1, c2, c3, c4 = st.columns(4)
            with c1: ap_p = st.text_input("Ap. Paterno*", value=st.session_state.get('det_ap_p', ''))
            with c2: ap_m = st.text_input("Ap. Materno*", value=st.session_state.get('det_ap_m', ''))
            with c3: nom1 = st.text_input("Primer Nombre*", value=st.session_state.get('det_nom1', ''))
            with c4: nom2 = st.text_input("Segundo Nombre", value=st.session_state.get('det_nom2', ''))
            
            c5, c6, c7 = st.columns(3)
            with c5: ced = st.text_input("Cédula*", value=st.session_state.get('cedula_busqueda', ''))
            with c6: fecha_nacimiento = st.date_input("Fecha de Nacimiento", min_value=datetime(1930, 1, 1))
            with c7: nacionalidad = st.text_input("Nacionalidad*", value="Ecuatoriana")
            
            c8, c9, c10 = st.columns(3)
            with c8: estado_civil = st.selectbox("Estado Civil", ["Soltero/a", "Casado/a", "Divorciado/a", "Viudo/a", "Unión de Hecho"])
            with c9: etnia = st.selectbox("Etnia", ["Mestizo", "Indígena", "Afroecuatoriano", "Montubio", "Blanco", "Otro"])
            with c10: prof = st.text_input("Profesión*", value=st.session_state.get('det_prof', ''))
            
            razon = st.text_area("Razón de Detención*")
            foto = st.file_uploader("Foto del Detenido*", type=["jpg", "png"], key=f"foto_det_{st.session_state['foto_key']}")
            
            if st.form_submit_button("Guardar Registro Detenido"):
                if ap_p and ap_m and nom1 and ced and razon and foto and validar_cedula(ced):
                    
                    # AQUÍ ESTÁ LA VARIABLE QUE FALTABA
                    fila_datos = [
                        st.session_state['upc_actual'],              
                        st.session_state['servidor_nombre'],         
                        st.session_state['servidor_cedula'],         
                        ap_p.upper(), ap_m.upper(), nom1.upper(), nom2.upper(), 
                        f"'{ced}", # <-- El apóstrofo protege el cero a la izquierda
                        str(datetime.today().date()), str(datetime.now().strftime("%H:%M:%S")),                                       
                    ]
                    
                    if guardar_registro_persona(fila_datos, db_doc):
                        # 1. Armamos los datos y generamos el PDF en memoria
                        datos_pdf = {
                            "UPC": st.session_state['upc_actual'],
                            "Fecha de Ingreso": str(datetime.today().date()),
                            "Hora de Ingreso": str(datetime.now().strftime("%H:%M:%S")),
                            "Nombres Completos": f"{ap_p.upper()} {ap_m.upper()} {nom1.upper()} {nom2.upper()}",
                            "C.I. Detenido": ced,
                            "Nacionalidad": nacionalidad.upper(),
                            "Profesión / Ocupación": prof.upper(),
                            "Servidor que Registra": f"{st.session_state['servidor_nombre']} (C.I: {st.session_state['servidor_cedula']})",
                            "Motivo de Detención": razon
                        }
                        st.session_state['pdf_detenido'] = generar_pdf_detenido(datos_pdf, foto)
                        st.session_state['pdf_detenido_name'] = f"Ingreso_Detenido_{ced}.pdf"
                        
                        # 2. Limpiamos y recargamos la interfaz (El botón aparecerá arriba)
                        limpiar_formulario_detenido()
                        st.rerun() 
                    else:
                        st.error("❌ Error al guardar en la nube.")
                else:
                    st.error("⚠️ Llene campos obligatorios y asegúrese de adjuntar la fotografía.")
                    # ==========================================
    # --- PESTAÑA VEHÍCULOS ---
    # ==========================================
    with tab_vehiculos:
        if 'foto_veh_key' not in st.session_state: st.session_state['foto_veh_key'] = 0
        
        # Variables para PDF de Ingreso
        if 'pdf_vehiculo' not in st.session_state: st.session_state['pdf_vehiculo'] = None
        if 'pdf_vehiculo_name' not in st.session_state: st.session_state['pdf_vehiculo_name'] = ""
        
        # Variables para PDF de Salida
        if 'pdf_vehiculo_salida' not in st.session_state: st.session_state['pdf_vehiculo_salida'] = None
        if 'pdf_vehiculo_salida_name' not in st.session_state: st.session_state['pdf_vehiculo_salida_name'] = ""

        def limpiar_formulario_vehiculo():
            st.session_state['placa_busqueda'] = ""
            st.session_state['foto_veh_key'] += 1

        # --- BOTÓN DE DESCARGA PARA INGRESO ---
        if st.session_state['pdf_vehiculo']:
            st.success("✅ Ingreso de vehículo guardado correctamente.")
            st.download_button(
                label="📄 Descargar Parte de Ingreso (PDF)",
                data=st.session_state['pdf_vehiculo'],
                file_name=st.session_state['pdf_vehiculo_name'],
                mime="application/pdf",
                type="primary"
            )
            if st.button("Finalizar y limpiar panel (Ingreso)"):
                st.session_state['pdf_vehiculo'] = None
                st.rerun()
            st.divider()

        # --- BOTÓN DE DESCARGA PARA SALIDA ---
        if st.session_state['pdf_vehiculo_salida']:
            st.success("✅ Salida de vehículo registrada correctamente.")
            st.download_button(
                label="📄 Descargar Parte de Salida (PDF)",
                data=st.session_state['pdf_vehiculo_salida'],
                file_name=st.session_state['pdf_vehiculo_salida_name'],
                mime="application/pdf",
                type="primary"
            )
            if st.button("Finalizar y limpiar panel (Salida)"):
                st.session_state['pdf_vehiculo_salida'] = None
                st.rerun()
            st.divider()

        st.subheader("🔍 Estado del Vehículo")
        
        col_v1, col_v2 = st.columns([3, 1])
        with col_v1:
            placa_input = st.text_input("Placa / Identificación", value=st.session_state.get('placa_busqueda', '')).upper().strip()
        with col_v2:
            st.write("")
            st.write("")
            if st.button("Buscar Vehículo", use_container_width=True):
                if placa_input:
                    st.session_state['placa_busqueda'] = placa_input

        if st.session_state.get('placa_busqueda', ''):
            placa = st.session_state['placa_busqueda']
            vehiculo_in = buscar_vehiculo(placa, db_doc)

            if vehiculo_in:
                st.warning(f"🚨 El vehículo **{placa}** está INGRESADO.")
                with st.form("form_salida_v", clear_on_submit=False):
                    st.markdown("**1. Datos del Servidor Policial que retira/traslada el vehículo**")
                    col_sp_ret1, col_sp_ret2 = st.columns(2)
                    with col_sp_ret1:
                        sp_retira = st.text_input("Grado, Nombres y Apellidos del SP*")
                    with col_sp_ret2:
                        cedula_sp_retira = st.text_input("Cédula del SP*", max_chars=10)

                    st.markdown("**2. Respaldo del Retiro**")
                    r_retira = st.text_area("Razón del retiro o traslado*")
                    
                    if st.form_submit_button("Registrar Salida de Vehículo"):
                        if sp_retira and cedula_sp_retira and r_retira and validar_cedula(cedula_sp_retira):
                            fecha_salida = str(datetime.today().date())
                            hora_salida = str(datetime.now().strftime("%H:%M:%S"))
                            
                            datos_salida = [
                                sp_retira.upper(), cedula_sp_retira, r_retira, 
                                fecha_salida, hora_salida
                            ]
                            
                            if actualizar_salida_vehiculo(placa, datos_salida, db_doc):
                                # 1. Armamos los datos para el PDF de salida
                                datos_pdf_salida = {
                                    "UPC": st.session_state['upc_actual'],
                                    "Placa / Identificación": placa,
                                    "Fecha de Salida": fecha_salida,
                                    "Hora de Salida": hora_salida,
                                    "Servidor que Retira/Traslada": f"{sp_retira.upper()} (C.I: {cedula_sp_retira})",
                                    "Razón de Retiro": r_retira,
                                    "Entregado por (Servidor de Turno)": f"{st.session_state['servidor_nombre']} (C.I: {st.session_state['servidor_cedula']})"
                                }
                                
                                # 2. Generamos el PDF en la memoria
                                st.session_state['pdf_vehiculo_salida'] = generar_pdf_salida_vehiculo(datos_pdf_salida)
                                st.session_state['pdf_vehiculo_salida_name'] = f"Salida_Vehiculo_{placa}.pdf"
                                
                                # 3. Recargamos la interfaz para mostrar el botón
                                limpiar_formulario_vehiculo() 
                                st.rerun() 
                            else:
                                st.error("❌ Error al actualizar la matriz.")
                        else:
                            st.error("⚠️ Llene los datos obligatorios y verifique la cédula.")
            else:
                st.info(f"✅ La placa **{placa}** no tiene ingresos activos. Llene el formulario para registrarlo.")
                with st.form("form_ingreso_v", clear_on_submit=False):
                    
                    st.markdown("**1. Datos del Vehículo**")
                    col_i1, col_i2 = st.columns(2)
                    with col_i1: chasis = st.text_input("Chasis / Motor*")
                    with col_i2: color = st.text_input("Color*")
                    
                    motivo = st.text_area("Motivo de ingreso del vehículo*")
                    foto_veh_ingreso = st.file_uploader("Foto del Vehículo*", type=["jpg", "png"], key=f"foto_veh_{st.session_state['foto_veh_key']}") 
                    
                    st.markdown("**2. Datos del Servidor Policial que ingresa el vehículo**")
                    col_of1, col_of2 = st.columns(2)
                    with col_of1: sp_ingresa = st.text_input("Grado, Nombres y Apellidos del SP*")
                    with col_of2: cedula_sp_ingresa = st.text_input("Número de Cédula del SP*", max_chars=10)
                    
                    if st.form_submit_button("Guardar Ingreso de Vehículo"):
                        if chasis and color and motivo and sp_ingresa and cedula_sp_ingresa and foto_veh_ingreso:
                            if validar_cedula(cedula_sp_ingresa):
                                fila_v = [
                                    st.session_state['upc_actual'],                                          
                                    f"{st.session_state['servidor_nombre']} ({st.session_state['servidor_cedula']})", 
                                    str(datetime.today().date()), str(datetime.now().strftime("%H:%M:%S")),                                
                                    placa, chasis.upper(), color.upper(), motivo,                                                                  
                                    sp_ingresa.upper(), cedula_sp_ingresa, "Ingresado"                                                              
                                ]
                                if guardar_ingreso_vehiculo(fila_v, db_doc):
                                    datos_pdf = {
                                        "UPC": st.session_state['upc_actual'],
                                        "Fecha Ingreso": str(datetime.today().date()),
                                        "Hora Ingreso": str(datetime.now().strftime("%H:%M:%S")),
                                        "Placa / Identificación": placa,
                                        "Chasis / Motor": chasis.upper(),
                                        "Color": color.upper(),
                                        "Servidor que Ingresa": f"{sp_ingresa.upper()} (C.I: {cedula_sp_ingresa})",
                                        "Motivo de Ingreso": motivo
                                    }
                                    st.session_state['pdf_vehiculo'] = generar_pdf_vehiculo(datos_pdf, foto_veh_ingreso)
                                    st.session_state['pdf_vehiculo_name'] = f"Ingreso_Vehiculo_{placa}.pdf"
                                    
                                    limpiar_formulario_vehiculo() 
                                    st.rerun() 
                                else:
                                    st.error("❌ Error al guardar en la nube.")
                            else:
                                st.error("⚠️ La cédula del Servidor Policial debe tener 10 dígitos.")
                        else:
                            st.error("⚠️ Faltan campos obligatorios por llenar (recuerde adjuntar la foto).")
