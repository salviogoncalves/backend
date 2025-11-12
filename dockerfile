# === Fase 1: Escolha da Imagem Base ===
# Esta instrução define a imagem base para o seu contêiner.
# Estamos usando uma imagem oficial do Python, versão 3.10, que é 'slim' (leve) e baseada em 'buster' (Debian 10).
# A versão 3.10 é boa e 'slim' ajuda a manter o tamanho final da imagem pequeno.
FROM python:3.10-bullseye

# === Fase 2: Configuração do Ambiente ===

# Define o diretório de trabalho padrão dentro do contêiner.
# Todos os comandos subsequentes (COPY, RUN, CMD) serão executados a partir deste diretório, a menos que especificado de outra forma.
WORKDIR /app

# === Fase 3: Instalação de Dependências de Sistema (FFmpeg) ===

# Atualiza a lista de pacotes e instala o FFmpeg.
# 'apt-get update': Atualiza a lista de pacotes disponíveis.
# 'apt-get install -y': Instala os pacotes. O '-y' responde 'sim' automaticamente a quaisquer prompts de instalação.
# '--no-install-recommends ffmpeg': Instala apenas o pacote 'ffmpeg' e suas dependências essenciais,
#    evitando pacotes "recomendados" que podem não ser estritamente necessários, para manter a imagem menor.
# 'rm -rf /var/lib/apt/lists/*': Limpa o cache do apt para reduzir ainda mais o tamanho da imagem final.
#    É uma prática comum após a instalação de pacotes de sistema.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# === Fase 4: Instalação de Dependências Python ===

# Copia apenas o arquivo requirements.txt para o contêiner.
# Fazemos isso em uma etapa separada para aproveitar o cache de camadas do Docker.
# Se apenas o código-fonte mudar e requirements.txt não, esta camada não será reconstruída.
COPY requirements.txt .

# Instala as dependências Python listadas em requirements.txt.
# 'pip install': Comando para instalar pacotes Python.
# '--no-cache-dir': Desativa o cache de pip para evitar o armazenamento de arquivos temporários, economizando espaço.
# '-r requirements.txt': Especifica o arquivo de onde ler as dependências.
RUN pip install --no-cache-dir -r requirements.txt

# === Fase 5: Copiar o Código da Aplicação ===

# Copia todo o conteúdo do diretório atual (localmente, onde está o Dockerfile)
# para o diretório de trabalho '/app' dentro do contêiner.
# Isso inclui main.py e quaisquer outros arquivos do seu projeto.
COPY . .

# === Fase 6: Configuração de Rede (Opcional, mas boa prática) ===

# Informa ao Docker que o contêiner ouvirá na porta 8000 em tempo de execução.
# Isso não publica a porta automaticamente, mas serve como documentação e pode ser usado por outras ferramentas.
EXPOSE 8000

# === Fase 7: Comando para Iniciar a Aplicação ===

# Este é o comando padrão que será executado quando o contêiner for iniciado.
# 'uvicorn main:app': Inicia sua aplicação FastAPI. 'main' é o nome do seu arquivo Python (main.py)
#    e 'app' é a instância da sua aplicação FastAPI (app = FastAPI(...)).
# '--host 0.0.0.0': Faz com que o Uvicorn ouça em todas as interfaces de rede dentro do contêiner.
# '--port 8000': Faz com que o Uvicorn ouça na porta 8000, que corresponde à porta EXPOSE.
# O Render substituirá a porta 8000 pela sua variável de ambiente $PORT em tempo de execução.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
# === Fase 1: Escolha da Imagem Base ===
FROM python:3.10-bullseye

# === Fase 2: Configuração do Ambiente ===
WORKDIR /app

# === Fase 3: Instalação de Dependências de Sistema (FFmpeg) ===
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# === Fase 4: Instalação de Dependências Python ===
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# === Fase 5: Copiar o Código da Aplicação ===
COPY . .

# === Fase 6: Configuração de Rede ===
EXPOSE 8000

# === Fase 7: Comando para Iniciar a Aplicação ===
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]