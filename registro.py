import streamlit as st
import re
from datetime import datetime
import pandas as pd
import gspread
import io
from google.oauth2.service_account import Credentials
import json

# --- CONFIGURACIÓN DE CARPETAS DE GOOGLE DRIVE ---
ID_CARPETA_DETENIDOS = "1pHWgZ-_ArJa-WLbBRoM_PWxFS34K0pDL"
ID_CARPETA_VEHICULOS = "1kTa2_mM5Ds6E5rhps8AH7IQaXNR6PPiC"

# ¡QUITAMOS EL SILENCIADOR PARA FORZAR EL ERROR VISUAL!
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

SCOPES_DRIVE = ['https://www.googleapis.com/auth/drive']
credenciales_texto = st.secrets["GOOGLE_CREDENTIALS_JSON"]
credenciales_info = json.loads(credenciales_texto)
creds_drive = Credentials.from_service_account_info(credenciales_info, scopes=SCOPES_DRIVE)
drive_service = build('drive', 'v3', credentials=creds_drive)


def subir_imagen_a_drive(foto_file, nombre_archivo, folder_id):
    """Sube la imagen a Drive y retorna su ID único."""
    if not drive_service: 
        # --- SEGUNDA ALARMA ---
        st.error("🚨 La imagen no se guardó porque el motor de Drive está apagado.")
        return None
    try:
        file_metadata = {'name': nombre_archivo, 'parents': [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(foto_file.getvalue()), mimetype=foto_file.type, resumable=True)
        archivo = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return archivo.get('id')
    except Exception as e:
        st.error(f"⚠️ Error al subir la imagen a Drive: {e}")
        return None

def obtener_imagen_drive(file_id):
    """Descarga la imagen desde Drive para mostrarla en pantalla."""
    if not drive_service or not file_id: return None
    try:
        request = drive_service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        return file.getvalue()
    except:
        return None

# Configuración básica de la página
st.set_page_config(page_title="Sistema de Registro UPC", layout="wide")

# --- CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource
def conectar_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    try:
        credenciales_texto = st.secrets["GOOGLE_CREDENTIALS_JSON"]
        credenciales_info = json.loads(credenciales_texto)
        credenciales = Credentials.from_service_account_info(credenciales_info, scopes=scopes)
        cliente = gspread.authorize(credenciales)
        
        SPREADSHEET_ID = "1QVluCNoVihqku69oKiXhbks3IZypaJRVaomSW0hzkOk"
        hoja_calculo = cliente.open_by_key(SPREADSHEET_ID)
        return hoja_calculo
    except Exception as e:
        st.error(f"⚠️ Error de conexión a la base de datos: {e}")
        return None
    
def validar_cedula(cedula):
    return bool(re.fullmatch(r'\d{10}', cedula))

# --- FUNCIONES DE BASE DE DATOS ---
def buscar_historial_persona(cedula, doc):
    if not doc: return []
    try:
        ws = doc.worksheet("Detenidos")
        datos = ws.get_all_records()
        df = pd.DataFrame(datos)
        if not df.empty:
            df.columns = df.columns.str.strip()
            col_cedula = 'Cédula' if 'Cédula' in df.columns else 'Cedula'
            if col_cedula in df.columns:
                # El .zfill(10) protege contra el borrado de ceros a la izquierda
                df[col_cedula] = df[col_cedula].astype(str).str.replace("'", "").str.strip().str.zfill(10)
                historial = df[df[col_cedula] == str(cedula).strip().zfill(10)]
                return historial.to_dict('records')
        return []
    except Exception as e:
        st.error(f"Error interno leyendo matriz: {e}")
        return []

def guardar_registro_persona(datos, doc):
    if not doc: return False
    try:
        ws = doc.worksheet("Detenidos")
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
            vehiculo = df[(df['Placa'] == str(placa)) & (df['Estado'] == 'Ingresado')]
            if not vehiculo.empty:
                return vehiculo.iloc[-1].to_dict()
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
            rango = f"K{fila}:P{fila}"
            ws.update(values=[["Retirado"] + datos_salida], range_name=rango)
            return True
        return False
    except Exception as e:
        st.error(f"Error en actualización: {e}")
        return False

db_doc = conectar_sheets()

# Inicializar variables de sesión
if 'turno_activo' not in st.session_state: st.session_state['turno_activo'] = False
if 'servidor_nombre' not in st.session_state: st.session_state['servidor_nombre'] = ""
if 'servidor_cedula' not in st.session_state: st.session_state['servidor_cedula'] = ""
if 'upc_actual' not in st.session_state: st.session_state['upc_actual'] = ""
if 'cedula_busqueda' not in st.session_state: st.session_state['cedula_busqueda'] = ""
if 'placa_busqueda' not in st.session_state: st.session_state['placa_busqueda'] = ""

st.title("Sistema de Gestión y Registro - UPC")

# --- INTERFAZ DEL TURNO ---
if not st.session_state['turno_activo']:
    st.header("1. Identificación del Servidor Policial en Guardia")
    with st.form("form_servidor"):
        lista_upcs = ["UPC San Miguel", "UPC Chimbo", "UPC San Pablo", "UPC Balsapamba", "UPC Telimbela", "UPC Santiago", "UPC Magdalena"]
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

    tab_detenidos, tab_vehiculos = st.tabs(["👤 Personas Detenidas", "🚗 Vehículos"])

    # ==========================================
    # --- PESTAÑA DETENIDOS ---
    # ==========================================
    with tab_detenidos:
        if 'foto_key' not in st.session_state: st.session_state['foto_key'] = 0

        def limpiar_formulario_detenido():
            for key in ['det_ap_p', 'det_ap_m', 'det_nom1', 'det_nom2', 'cedula_busqueda', 'det_prof', 'det_carac']:
                st.session_state[key] = ""
            st.session_state['foto_key'] += 1

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
                        with st.expander(f"Ficha #{idx+1} - {fecha_reg} | {upc_reg}", expanded=(idx == len(historial)-1)):
                            col_info, col_foto = st.columns([2, 1])
                            with col_info:
                                st.write(f"**Motivo:** {reg.get('Razón Detención', 'No especificado')}")
                                st.write(f"**Características Físicas:** {reg.get('Características Físicas', 'No registradas')}")
                                st.write(f"**Registrado por:** {reg.get('Nombre Servidor', 'Desconocido')}")
                            with col_foto:
                                foto_id = reg.get('Foto ID', '')
                                if foto_id:
                                    with st.spinner("Cargando foto..."):
                                        img_bytes = obtener_imagen_drive(foto_id)
                                        if img_bytes:
                                            st.image(img_bytes, use_column_width=True)
                                        else:
                                            st.info("Imagen no disponible")
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
            
            caracteristicas = st.text_area("Características Físicas (Tatuajes, cicatrices, vestimenta, etc.)*", value=st.session_state.get('det_carac', ''))
            razon = st.text_area("Razón de Detención*")
            foto = st.file_uploader("Foto del Detenido*", type=["jpg", "png", "jpeg"], key=f"foto_det_{st.session_state['foto_key']}")
            
            if st.form_submit_button("Guardar Registro Detenido"):
                if ap_p and ap_m and nom1 and ced and razon and caracteristicas and foto and validar_cedula(ced):
                    
                    with st.spinner("Subiendo fotografía a la matriz..."):
                        nombre_foto = f"DET_{ced}_{datetime.now().strftime('%Y%m%d%H%M')}.jpg"
                        foto_id_drive = subir_imagen_a_drive(foto, nombre_foto, ID_CARPETA_DETENIDOS)
                        
                    fila_datos = [
                        st.session_state['upc_actual'], st.session_state['servidor_nombre'], st.session_state['servidor_cedula'],         
                        ap_p.upper(), ap_m.upper(), nom1.upper(), nom2.upper(), ced,                                         
                        str(datetime.today().date()), str(datetime.now().strftime("%H:%M:%S")),    
                        str(fecha_nacimiento), prof.upper(), nacionalidad.upper(),                        
                        estado_civil, etnia, razon, caracteristicas, foto_id_drive or ""                                        
                    ]
                    
                    if guardar_registro_persona(fila_datos, db_doc):
                        st.success("✅ Registro guardado en la matriz exitosamente.")
                        limpiar_formulario_detenido()
                        st.rerun() 
                    else:
                        st.error("❌ Error al guardar en la nube.")
                else:
                    st.error("⚠️ Llene todos los campos obligatorios y asegúrese de adjuntar la fotografía.")

    # ==========================================
    # --- PESTAÑA VEHÍCULOS ---
    # ==========================================
    with tab_vehiculos:
        if 'foto_veh_key' not in st.session_state: st.session_state['foto_veh_key'] = 0
        
        def limpiar_formulario_vehiculo():
            st.session_state['placa_busqueda'] = ""
            st.session_state['foto_veh_key'] += 1

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
                
                # Mostrar foto del vehículo ingresado
                foto_id_v = vehiculo_in.get('Foto ID', '')
                if foto_id_v:
                    with st.spinner("Cargando foto del vehículo..."):
                        img_bytes = obtener_imagen_drive(foto_id_v)
                        if img_bytes:
                            st.image(img_bytes, caption=f"Fotografía de Ingreso - {placa}", width=400)
                
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
                            
                            datos_salida = [sp_retira.upper(), cedula_sp_retira, r_retira, fecha_salida, hora_salida]
                            
                            if actualizar_salida_vehiculo(placa, datos_salida, db_doc):
                                st.success("✅ Salida registrada exitosamente.")
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
                    foto_veh_ingreso = st.file_uploader("Foto del Vehículo*", type=["jpg", "png", "jpeg"], key=f"foto_veh_{st.session_state['foto_veh_key']}") 
                    
                    st.markdown("**2. Datos del Servidor Policial que ingresa el vehículo**")
                    col_of1, col_of2 = st.columns(2)
                    with col_of1: sp_ingresa = st.text_input("Grado, Nombres y Apellidos del SP*")
                    with col_of2: cedula_sp_ingresa = st.text_input("Número de Cédula del SP*", max_chars=10)
                    
                    if st.form_submit_button("Guardar Ingreso de Vehículo"):
                        if chasis and color and motivo and sp_ingresa and cedula_sp_ingresa and foto_veh_ingreso:
                            if validar_cedula(cedula_sp_ingresa):
                                
                                with st.spinner("Subiendo fotografía a la matriz..."):
                                    nombre_foto = f"VEH_{placa}_{datetime.now().strftime('%Y%m%d%H%M')}.jpg"
                                    foto_id_drive = subir_imagen_a_drive(foto_veh_ingreso, nombre_foto, ID_CARPETA_VEHICULOS)
                                
                                fila_v = [
                                    st.session_state['upc_actual'], f"{st.session_state['servidor_nombre']} ({st.session_state['servidor_cedula']})", 
                                    str(datetime.today().date()), str(datetime.now().strftime("%H:%M:%S")),                                
                                    placa, chasis.upper(), color.upper(), motivo,                                                                  
                                    sp_ingresa.upper(), cedula_sp_ingresa, "Ingresado", foto_id_drive or ""                                                              
                                ]
                                if guardar_ingreso_vehiculo(fila_v, db_doc):
                                    st.success("✅ Ingreso de vehículo guardado correctamente.")
                                    limpiar_formulario_vehiculo() 
                                    st.rerun() 
                                else:
                                    st.error("❌ Error al guardar en la nube.")
                            else:
                                st.error("⚠️ La cédula del Servidor Policial debe tener 10 dígitos.")
                        else:
                            st.error("⚠️ Faltan campos obligatorios por llenar (recuerde adjuntar la foto).")
