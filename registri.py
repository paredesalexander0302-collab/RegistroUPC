import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from fpdf import FPDF
import tempfile
import os
import traceback
# ==========================================
# CONFIGURACIÓN DE GOOGLE SHEETS
# ==========================================
def get_google_sheet(sheet_name):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Leemos directamente los secretos de la nube
    creds_dict = dict(st.secrets["gcp_service_account"])
    
    # === EL PARCHE MÁGICO AQUÍ ===
    # Esto fuerza al sistema a interpretar los \n como verdaderos saltos de línea
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    # =============================
    
    # Autenticamos
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open("Registro_UPC").worksheet(sheet_name)
    
    return sheet

# ==========================================
# GENERADOR DE PDF CON MARCA DE AGUA
# ==========================================
class FichaPDF(FPDF):
    def header(self):
        try:
            with self.local_context(fill_opacity=0.15):
                self.image('logo_policia.png', x=45, y=80, w=120)
        except:
            pass 
        
        self.set_font('helvetica', 'B', 14)
        self.cell(0, 10, 'POLICÍA NACIONAL DEL ECUADOR', border=0, ln=1, align='C')
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 10, 'FICHA DE REGISTRO - UPC', border=0, ln=1, align='C')
        self.ln(10)

def generar_pdf_detenido(datos, foto_path):
    pdf = FichaPDF()
    pdf.add_page()
    pdf.set_font('helvetica', '', 11)
    
    for key, value in datos.items():
        texto_valor = str(value).strip() if str(value).strip() else "No registrado"
        
        pdf.set_font('helvetica', 'B', 11)
        pdf.cell(50, 8, f"{key}:", ln=0)
        pdf.set_font('helvetica', '', 11)
        pdf.multi_cell(140, 8, texto_valor)
    
    if foto_path:
        pdf.ln(10)
        pdf.cell(0, 10, 'Fotografía del Detenido:', ln=1)
        pdf.image(foto_path, x=10, w=60)
        
    temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(temp_pdf.name)
    return temp_pdf.name

# ==========================================
# INTERFAZ STREAMLIT
# ==========================================
st.set_page_config(page_title="Sistema de Registro UPC", layout="wide")

st.title("Sistema de Gestión y Registro - UPC")

with st.sidebar:
    st.header("Datos de Guardia")
    upc_actual = st.selectbox("Identificación del UPC", ["UPC San Miguel 1", "UPC San Miguel 2", "UPC Centro", "Otro"])
    nombre_servidor = st.text_input("Grado y Nombres del Servidor")
    cedula_servidor = st.text_input("Cédula del Servidor")
    st.divider()
    st.write(f"**Fecha actual:** {datetime.now().strftime('%Y-%m-%d')}")

tab1, tab2 = st.tabs(["Registro de Detenidos", "Registro de Vehículos"])

# ==========================================
# PESTAÑA 1: DETENIDOS
# ==========================================
with tab1:
    st.header("Ingreso de Detenidos / Aprehendidos")
    
    col_busqueda, col_btn = st.columns([3, 1])
    with col_busqueda:
        buscar_cedula = st.text_input("Ingrese cédula para verificar antecedentes en este UPC:")
    with col_btn:
        st.write("")
        st.write("")
        if st.button("Verificar Historial"):
            try:
                sheet_detenidos = get_google_sheet("Detenidos")
                registros = sheet_detenidos.get_all_records()
                df = pd.DataFrame(registros)
                if not df.empty and 'Cédula' in df.columns:
                    resultados = df[df['Cédula'].astype(str) == str(buscar_cedula)]
                    if not resultados.empty:
                        st.success(f"Se encontraron {len(resultados)} registro(s) previo(s).")
                        st.dataframe(resultados)
                    else:
                        st.info("No existen registros previos para esta cédula.")
            except Exception as e:
                st.error(f"Error al conectar con la base de datos: {e}")

    st.subheader("Nuevo Registro")
    
    # ---------------------------------------------------------
    # FORMULARIO
    # ---------------------------------------------------------
    with st.form("form_detenidos"):
        col1, col2, col3 = st.columns(3)
        with col1:
            ap_paterno = st.text_input("Apellido Paterno")
            ap_materno = st.text_input("Apellido Materno")
            primer_nombre = st.text_input("Primer Nombre")
            segundo_nombre = st.text_input("Segundo Nombre")
        with col2:
            cedula_detenido = st.text_input("Cédula de Identidad")
            fecha_nacimiento = st.date_input("Fecha de Nacimiento", min_value=datetime(1930, 1, 1))
            nacionalidad = st.text_input("Nacionalidad", "Ecuatoriana")
            etnia = st.selectbox("Etnia", ["Mestizo", "Indígena", "Afroecuatoriano", "Blanco", "Montubio", "Otro"])
        with col3:
            estado_civil = st.selectbox("Estado Civil", ["Soltero/a", "Casado/a", "Divorciado/a", "Viudo/a", "Unión Libre"])
            profesion = st.text_input("Profesión / Ocupación")
            fecha_ingreso = st.date_input("Fecha de Ingreso")
            hora_ingreso = st.time_input("Hora de Ingreso")
            
        razon_detencion = st.text_area("Motivo / Razón de la Detención")
        foto_upload = st.file_uploader("Subir Fotografía del Detenido", type=['jpg', 'png', 'jpeg'])
        
        submit_detenido = st.form_submit_button("Guardar Registro y Generar Ficha")
        
    # ---------------------------------------------------------
    # LÓGICA FUERA DEL FORMULARIO (Misma sangría que 'with st.form')
    # ---------------------------------------------------------
    if submit_detenido:
        if not nombre_servidor or not cedula_servidor:
            st.error("Debe llenar los datos del servidor policial en la barra lateral.")
        else:
            try:
                datos_guardar = [
                    upc_actual, nombre_servidor, cedula_servidor,
                    ap_paterno, ap_materno, primer_nombre, segundo_nombre, cedula_detenido,
                    str(fecha_ingreso), str(hora_ingreso), str(fecha_nacimiento), profesion,
                    nacionalidad, estado_civil, etnia, razon_detencion
                ]
                
                sheet_detenidos = get_google_sheet("Detenidos")
                sheet_detenidos.append_row(datos_guardar)
                st.success("¡Registro guardado en la nube exitosamente!")
                
                foto_path = None
                if foto_upload:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_foto:
                        tmp_foto.write(foto_upload.read())
                        foto_path = tmp_foto.name
                
                datos_dict = {
                    "UPC": upc_actual,
                    "Servidor a cargo": f"{nombre_servidor} (C.I. {cedula_servidor})",
                    "Nombres Completos": f"{ap_paterno} {ap_materno} {primer_nombre} {segundo_nombre}",
                    "Cédula": cedula_detenido,
                    "Fecha/Hora Ingreso": f"{fecha_ingreso} {hora_ingreso}",
                    "Nacionalidad / Etnia": f"{nacionalidad} / {etnia}",
                    "Razón": razon_detencion
                }
                
                pdf_file = generar_pdf_detenido(datos_dict, foto_path)
                
                with open(pdf_file, "rb") as f:
                    st.download_button("Descargar Ficha PDF", f, file_name=f"Ficha_{cedula_detenido}.pdf", mime="application/pdf")
                    
            except Exception as e:
                st.error("Error detallado:")
                st.code(traceback.format_exc())
# ==========================================
# PESTAÑA 2: VEHÍCULOS
# ==========================================
with tab2:
    st.header("Gestión de Vehículos Retenidos/Ingresados")
    
    tipo_registro = st.radio("Acción a realizar:", ["Ingreso de Vehículo", "Salida de Vehículo"])
    
    if tipo_registro == "Ingreso de Vehículo":
        with st.form("form_ingreso_vehiculo"):
            col1, col2 = st.columns(2)
            with col1:
                placa = st.text_input("Placas del Vehículo")
                chasis = st.text_input("Número de Chasis / Motor")
                color = st.text_input("Color")
            with col2:
                fecha_v = st.date_input("Fecha de Ingreso")
                hora_v = st.time_input("Hora de Ingreso")
                quien_ingresa = st.text_input("Grado, Nombres y C.I. de quien ingresa")
            
            submit_v_in = st.form_submit_button("Registrar Ingreso")
            
        if submit_v_in:
            if not nombre_servidor:
                st.error("Ingrese el nombre del servidor en la barra lateral.")
            else:
                try:
                    datos_v = [upc_actual, "INGRESO", placa, chasis, color, str(fecha_v), str(hora_v), quien_ingresa, nombre_servidor]
                    sheet_vehiculos = get_google_sheet("Vehiculos")
                    sheet_vehiculos.append_row(datos_v)
                    st.success("Ingreso de vehículo registrado en la nube.")
                except Exception as e:
                    st.error(f"Ocurrió un error al guardar: {e}")
    
    else:
        with st.form("form_salida_vehiculo"):
            st.info("Generación de Documento de Salida")
            placa_salida = st.text_input("Placas del Vehículo a Retirar")
            quien_retira = st.text_input("Nombres, Apellidos y Cédula de la persona que retira")
            razon_salida = st.text_area("Razón de la salida / Disposición legal")
            fecha_salida = st.date_input("Fecha de Salida")
            hora_salida = st.time_input("Hora de Salida")
            
            submit_v_out = st.form_submit_button("Registrar Salida y Generar Acta")
            
        if submit_v_out:
            if not nombre_servidor:
                st.error("Ingrese el nombre del servidor en la barra lateral.")
            else:
                try:
                    datos_v_out = [upc_actual, "SALIDA", placa_salida, "", "", str(fecha_salida), str(hora_salida), quien_retira, razon_salida, nombre_servidor]
                    sheet_vehiculos = get_google_sheet("Vehiculos")
                    sheet_vehiculos.append_row(datos_v_out)
                    st.success("Salida registrada en la nube.")
                        
                    datos_salida = {
                        "UPC": upc_actual,
                        "Vehículo Placa": placa_salida,
                        "Retirado por": quien_retira,
                        "Razón / Orden": razon_salida,
                        "Fecha y Hora": f"{fecha_salida} {hora_salida}",
                        "Entregado por (Guardia)": nombre_servidor
                    }
                    pdf_salida = generar_pdf_detenido(datos_salida, None)
                    
                    with open(pdf_salida, "rb") as f:
                        st.download_button("Descargar Acta de Salida", f, file_name=f"Salida_{placa_salida}.pdf", mime="application/pdf")
                except Exception as e:
                    st.error(f"Ocurrió un error: {e}")
