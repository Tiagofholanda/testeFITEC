import streamlit as st
import pandas as pd
import geopandas as gpd
from pyproj import Transformer
import leafmap.foliumap as leafmap
from PIL import Image
import base64
import folium
from folium.plugins import HeatMap, TimestampedGeoJson, LocateControl
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# Função para carregar os dados do Excel e corrigir coordenadas
def load_data(file_path):
    try:
        df = pd.read_excel(file_path)
        
        if 'Data' in df.columns:
            df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
        else:
            st.error("A coluna 'Data' não foi encontrada no arquivo Excel.")
        
        # Substituir vírgulas por pontos nas coordenadas
        df['POINT_X'] = df['POINT_X'].astype(str).str.replace(',', '.').astype(float)
        df['POINT_Y'] = df['POINT_Y'].astype(str).str.replace(',', '.').astype(float)
        
        return df
    except Exception as e:
        st.error(f"Erro ao ler o arquivo Excel: {e}")
        return None

# Função para converter UTM para graus decimais
def convert_utm_to_latlon(df, utm_zone="22S"):
    transformer = Transformer.from_crs(f"epsg:31982", "epsg:4326", always_xy=True)  # EPSG:31982 = SIRGAS 2000 / UTM zone 22S
    df['Longitude'], df['Latitude'] = transformer.transform(df['POINT_X'].values, df['POINT_Y'].values)
    return df

# Função para aplicar filtros de atributos
def apply_attribute_filters(df, filters):
    for col, values in filters.items():
        if values and len(values) != len(df[col].unique()):
            df = df[df[col].isin(values)]
    return df

# Função para converter DataFrame para GeoJSON
def convert_to_geojson(df):
    try:
        if 'Longitude' in df.columns and 'Latitude' in df.columns:
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.Longitude, df.Latitude), crs="EPSG:4326")
            if not gdf.empty:
                geojson_file = "output.geojson"
                gdf.to_file(geojson_file, driver="GeoJSON")
                return geojson_file, gdf
            else:
                st.error("O GeoDataFrame está vazio. Verifique os dados filtrados.")
                return None, None
        else:
            st.error("O arquivo Excel não contém colunas 'Longitude' e 'Latitude'.")
            return None, None
    except Exception as e:
        st.error(f"Erro ao converter para GeoJSON: {e}")
        return None, None

# Função para adicionar o logo ao mapa
def add_logo_to_map(m, logo_path):
    with open(logo_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode()

    logo_html = f'''
    <div style="position: fixed; 
                bottom: 10px; right: 10px; 
                z-index: 9999; 
                width: 100px; 
                height: 100px;">
        <img src="data:image/png;base64,{encoded_string}" style="width: 100%; height: 100%;">
    </div>
    '''
    logo_element = folium.Element(logo_html)
    m.get_root().html.add_child(logo_element)

# Função para criar o mapa com evolução temporal
def create_map(gdf, basemap_option, logo_path, legend_column=None, color_map=None, generate_heatmap=False, generate_time_series=False):
    m = leafmap.Map(center=[gdf['Latitude'].mean(), gdf['Longitude'].mean()], zoom=10)
    
    if basemap_option == "Google Maps":
        m.add_basemap("ROADMAP")
    elif basemap_option == "Google Satellite":
        m.add_basemap("SATELLITE")
    elif basemap_option == "Google Terrain":
        m.add_basemap("TERRAIN")
    elif basemap_option == "ESRI Satellite":
        m.add_basemap("Esri.WorldImagery")
    elif basemap_option == "ESRI Street":
        m.add_basemap("Esri.WorldStreetMap")
    else:
        m.add_basemap("openstreetmap")

    add_logo_to_map(m, logo_path)

    LocateControl(auto_start=False).add_to(m)

    if generate_heatmap:
        heat_data = [[row['Latitude'], row['Longitude']] for _, row in gdf.iterrows()]
        HeatMap(heat_data).add_to(m)

    if generate_time_series and 'Data' in gdf.columns:
        features = []
        for _, row in gdf.iterrows():
            if pd.notnull(row['Data']):
                feature = {
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [row['Longitude'], row['Latitude']],
                    },
                    'properties': {
                        'time': row['Data'].isoformat(),
                        'popup': row[legend_column] if legend_column else '',
                        'style': {'color': color_map.get(row[legend_column], 'blue') if color_map else 'blue'}
                    }
                }
                features.append(feature)

        if features:
            time_geojson = {
                'type': 'FeatureCollection',
                'features': features,
            }

            TimestampedGeoJson(
                data=time_geojson,
                period='P1D',
                add_last_point=True,
                auto_play=False,
                loop=False,
                max_speed=1,
                loop_button=True,
                date_options='YYYY-MM-DD',
                time_slider_drag_update=True
            ).add_to(m)
        else:
            st.error("Nenhum dado disponível para criar o mapa temporal.")

    if legend_column and color_map:
        for _, row in gdf.iterrows():
            folium.CircleMarker(location=[row['Latitude'], row['Longitude']],
                                radius=5,
                                color=color_map[row[legend_column]],
                                fill=True,
                                fill_color=color_map[row[legend_column]],
                                fill_opacity=0.7).add_to(m)

        legend_html = f'''
        <div style="position: fixed; 
                    bottom: 50px; right: 50px; 
                    z-index: 9999; 
                    background-color: white;
                    padding: 10px; 
                    border: 2px solid grey;
                    border-radius: 5px;">
        <h4>Legenda</h4>
        '''
        for value, color in color_map.items():
            legend_html += f'<i style="background:{color}; width: 20px; height: 20px; float:left; margin-right: 10px;"></i>{value}<br>'
        legend_html += '</div>'
        legend_element = folium.Element(legend_html)
        m.get_root().html.add_child(legend_element)

    return m

# Função para salvar o mapa como HTML
def save_map_as_html(m):
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_file = f"mapa_interativo_{current_time}.html"
    m.save(html_file)
    st.sidebar.success(f"Mapa salvo como {html_file}")

# Função para criar gráficos de estatísticas simples
def create_statistics_chart(df, column_name, color_map):
    # Calcula as estatísticas descritivas e a contagem por valor
    counts = df[column_name].value_counts()
    total_count = counts.sum()
    percentages = (counts / total_count) * 100

    # Cria DataFrame para o gráfico
    stats_df = pd.DataFrame({
        'Categoria': counts.index,
        'Contagem': counts.values,
        'Percentual': percentages.values
    })

    # Ajusta as cores
    colors = [color_map.get(val, '#1f77b4') for val in stats_df['Categoria']]

    # Cria o gráfico de barras
    fig_bar = px.bar(stats_df, x='Categoria', y='Contagem',
                     text='Contagem', color='Categoria', color_discrete_sequence=colors,
                     title=f'Estatísticas da Coluna "{column_name}"')

    # Melhora a aparência do gráfico de barras
    fig_bar.update_traces(texttemplate='%{text}', textposition='outside', marker=dict(line=dict(color='black', width=1)))
    fig_bar.update_layout(yaxis_title='Contagem', xaxis_title='Categoria',
                          title_x=0.5, title_font_size=24, title_font_color='navy', 
                          margin=dict(l=50, r=50, t=50, b=50), 
                          plot_bgcolor='rgba(240, 240, 240, 0.8)',
                          paper_bgcolor='rgba(255, 255, 255, 0.8)')

    # Cria o gráfico de donut
    fig_donut = go.Figure(data=[go.Pie(labels=stats_df['Categoria'], values=stats_df['Percentual'],
                                       hole=0.5, marker=dict(colors=colors), 
                                       textinfo='label+percent', insidetextorientation='auto')])

    fig_donut.update_layout(title_text=f'Porcentagens da Coluna "{column_name}"',
                            title_x=0.5, title_font_size=24, title_font_color='navy', 
                            margin=dict(l=50, r=50, t=50, b=50),
                            plot_bgcolor='rgba(240, 240, 240, 0.8)',
                            paper_bgcolor='rgba(255, 255, 255, 0.8)')

    return fig_bar, fig_donut

# Título da aplicação
st.title("WebGIS Interativo com Conversão para GeoJSON")

# Caminho para o logo da empresa
logo_path = r"C:\Users\Tiago Holanda NMC\Desktop\MAC - Mapas\logo\logo.png"

# Adicionar o logo na interface do Streamlit
image = Image.open(logo_path)
st.image(image, width=200)

# Caminho para o arquivo Excel
excel_file = r"C:\Users\Tiago Holanda NMC\Desktop\projeto\Dados\teste-poc\teste-heithor.xlsx"

# Carregar os dados do arquivo Excel
df = load_data(excel_file)

if df is not None:
    st.write("Dados carregados com sucesso!")

    # Converte as coordenadas UTM para graus decimais (latitude e longitude) na zona 22S
    df = convert_utm_to_latlon(df, utm_zone="22S")

    # Remover as colunas de coordenadas da visualização
    df_to_display = df.drop(columns=['POINT_X', 'POINT_Y', 'Longitude', 'Latitude'])

    filter_columns = st.sidebar.multiselect(
        "Escolha as colunas para aplicar filtros:",
        options=df_to_display.columns,
        default=[]
    )

    filters = {}

    if filter_columns:
        for col in filter_columns:
            unique_vals = df_to_display[col].unique().tolist()
            selected_vals = st.sidebar.multiselect(f"Filtrar por '{col}'", unique_vals, default=unique_vals)
            filters[col] = selected_vals

        df_filtered = apply_attribute_filters(df_to_display, filters)

        legend_column = st.sidebar.selectbox(
            "Escolha a coluna para gerar a legenda:",
            options=[None] + filter_columns
        )

        color_map = {}

        if legend_column:
            unique_values = df_filtered[legend_column].unique()
            for value in unique_values:
                color = st.sidebar.color_picker(f"Escolha a cor para {value}", "#3388ff")
                color_map[value] = color

        geojson_file, gdf = convert_to_geojson(df)

        if geojson_file is not None and gdf is not None:
            st.sidebar.title("Configurações do Mapa")
            basemap_option = st.sidebar.selectbox(
                "Escolha o mapa base", 
                ["OpenStreetMap", "Google Maps", "Google Satellite", "Google Terrain", "ESRI Satellite", "ESRI Street"]
            )

            generate_heatmap = st.sidebar.checkbox("Gerar mapa de calor")
            generate_time_series = st.sidebar.checkbox("Gerar evolução temporal")

            m = create_map(gdf, basemap_option, logo_path, legend_column=legend_column, color_map=color_map, generate_heatmap=generate_heatmap, generate_time_series=generate_time_series)

            m.add_geojson(geojson_file, layer_name="Dados GeoJSON")

            st.subheader("Mapa Interativo")
            m.to_streamlit(height=600)

            # Adicionar gráficos de estatísticas abaixo do mapa
            if 'Analise' in df_filtered.columns:
                st.subheader("Estatísticas da Coluna 'Analise'")
                
                # Gráfico de barras
                fig_bar, fig_donut = create_statistics_chart(df_filtered, 'Analise', color_map)
                
                st.plotly_chart(fig_bar, use_container_width=True)
                st.plotly_chart(fig_donut, use_container_width=True)

            if st.sidebar.button("Salvar mapa como HTML"):
                save_map_as_html(m)

            st.subheader("Tabela de Dados Filtrados")
            st.write(df_filtered)

            st.subheader("Colunas disponíveis no DataFrame")
            st.write(df_to_display.columns)
        else:
            st.error("Falha ao converter os dados para GeoJSON.")
    else:
        st.warning("Nenhuma coluna selecionada para filtrar. Selecione as colunas na barra lateral.")
else:
    st.error("Falha ao carregar os dados.")
