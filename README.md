# 🎬 Manager-SRT

**Gerenciador Profissional de Legendas e Arquivos de Mídia**

<div align="center">

[![Version](https://img.shields.io/badge/version-1.1.5-blue.svg)](https://github.com/talesam/manager-srt)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Bash](https://img.shields.io/badge/bash-4.0%2B-orange.svg)](https://www.gnu.org/software/bash/)

</div>

Script Bash avançado para organizar automaticamente legendas e arquivos de mídia em bibliotecas de filmes e séries.

## ✨ Características

- 🔍 **Preview Detalhado** - Veja exatamente o que será feito antes de executar
- 🎨 **Interface Colorida** - Output visualmente organizado e intuitivo
- 🛡️ **Backup Automático** - Proteção antes de qualquer modificação
- 📝 **Sistema de Logs** - Auditoria completa de todas as operações
- ⚙️ **Altamente Configurável** - 20+ opções de linha de comando
- 🤖 **Automação Completa** - Perfeito para scripts e cron jobs
- 🧠 **Detecção Inteligente** - Identifica legendas em português automaticamente
- 🚀 **Zero Dependências Externas** - Apenas Bash puro

## 📦 O que o Script Faz

### Operações Automáticas

1. **Renomeia legendas `.por2.srt` → `.por.srt`**
   - Corrige nomenclatura não padrão
   - Evita duplicação de idioma

2. **Adiciona código de idioma a legendas sem extensão**
   - Detecta português automaticamente
   - `legenda.srt` → `legenda.por.srt`

3. **Remove legendas em outros idiomas**
   - Mais de 40 códigos de idioma suportados
   - eng, spa, fre, ger, ita, rus, chi, jpn, kor, e muitos outros

4. **Remove arquivos indesejados**
   - Imagens: jpg, png, gif, bmp
   - Metadados: nfo

5. **Remove diretórios metadata**
   - Limpa diretórios de metadados vazios ou desnecessários

## 🚀 Instalação

### Instalação Rápida

```bash
# Download
wget https://raw.githubusercontent.com/talesam/manager-srt/main/manager-srt
# OU
curl -O https://raw.githubusercontent.com/talesam/manager-srt/main/manager-srt

# Dar permissão de execução
chmod +x manager-srt

# Mover para PATH (opcional)
sudo mv manager-srt /usr/local/bin/
```

### Instalação Manual

```bash
# Clonar repositório
git clone https://github.com/talesam/manager-srt.git
cd manager-srt

# Dar permissão
chmod +x manager-srt

# Instalar globalmente (opcional)
sudo cp manager-srt /usr/local/bin/
```

### Verificar Instalação

```bash
manager-srt --version
# Saída: manager-srt versão 1.0.4
```

## 📖 Uso

### Uso Básico

```bash
# 1. Ver o que será feito (RECOMENDADO)
manager-srt --dry-run

# 2. Se estiver ok, executar
manager-srt
```

### Quick Start

```bash
# No diretório do filme/série
cd /media/filmes/Matrix
manager-srt --dry-run    # Preview
manager-srt              # Executar
```

### Opções Principais

```bash
# Ver ajuda completa
manager-srt --help

# Preview sem executar
manager-srt --dry-run

# Executar sem confirmação
manager-srt --yes

# Modo silencioso (para automação)
manager-srt --quiet --yes

# Modo verboso (debug)
manager-srt --verbose

# Com backup
manager-srt --backup /tmp/backup

# Com log
manager-srt --log /var/log/manager-srt.log

# Trabalhar em outro diretório
manager-srt --workdir /media/series/Breaking\ Bad/Season\ 1
```

### Controle de Operações

```bash
# Apenas renomear .por2.srt
manager-srt --only-rename-por2

# Apenas adicionar idioma a legendas
manager-srt --only-rename-no-lang

# Apenas remover arquivos indesejados
manager-srt --only-remove-unwanted

# Apenas remover diretórios metadata
manager-srt --only-remove-metadata

# Desabilitar operações específicas
manager-srt --no-remove-metadata --no-rename-por2
```

### Configurações Avançadas

```bash
# Ajustar sensibilidade de detecção de PT
manager-srt --min-pt-words 3    # Mais flexível
manager-srt --min-pt-words 10   # Mais rigoroso

# Combinação completa
manager-srt \
    --workdir /media/downloads \
    --backup /backup/legendas \
    --log /var/log/manager.log \
    --min-pt-words 7 \
    --verbose \
    --yes
```

## 📋 Exemplos Práticos

### Exemplo 1: Primeiro Uso (Seguro)

```bash
# Navegar até o diretório
cd /media/filmes/Inception

# Ver preview
manager-srt --dry-run

# Output mostrará:
# ═══════════════════════════════════════════
# 📋 PREVIEW DAS OPERAÇÕES
# ═══════════════════════════════════════════
# 
# 1. Renomear .por2.srt → .por.srt (2 arquivos)
#    → Inception.por2.srt → Inception.por.srt
#    → Extras.por2.srt → Extras.por.srt
#
# 2. Remover arquivos indesejados (5 arquivos)
#    ✗ 3 arquivo(s) .eng.srt
#    ✗ 2 arquivo(s) .jpg
#
# 📊 Total: 7 operações

# Se estiver ok, executar
manager-srt
```

### Exemplo 2: Processar Série Completa

```bash
# Script para processar todas as temporadas
for season in /media/series/Breaking\ Bad/Season*; do
    echo "Processando: $(basename "$season")"
    manager-srt --workdir "$season" --yes --quiet
done
```

### Exemplo 3: Cron Job Automático

```bash
# Adicionar ao crontab (crontab -e)
# Processar downloads a cada hora
0 * * * * /usr/local/bin/manager-srt --workdir /media/downloads --yes --quiet --log /var/log/manager-srt-cron.log
```

### Exemplo 4: Máxima Segurança

```bash
# Backup + Log + Preview antes
manager-srt --dry-run
manager-srt --backup /backup/$(date +%Y%m%d) --log /var/log/manager.log
```

## 🎨 Saída do Script

### Preview Detalhado

```
╔════════════════════════════════════════════════════════════════════════╗
║  GERENCIADOR DE LEGENDAS E ARQUIVOS DE MÍDIA v1.0.4                    ║
╚════════════════════════════════════════════════════════════════════════╝

[INFO] Diretório de trabalho: /media/filmes/Matrix
[INFO] Escaneando diretório: /media/filmes/Matrix
────────────────────────────────────────────────────────────────────────
[INFO] 🔍 Procurando arquivos .por2.srt...
   ✓ Encontrados: 2 arquivos
[INFO] 🔍 Procurando legendas sem idioma...
   ✓ Encontrados: 1 arquivos
[INFO] 🔍 Procurando arquivos indesejados...
   ✓ Encontrados: 8 arquivos
────────────────────────────────────────────────────────────────────────

════════════════════════════════════════════════════════════════════════
📋 PREVIEW DAS OPERAÇÕES
════════════════════════════════════════════════════════════════════════

1. Renomear arquivos .por2.srt → .por.srt (2 arquivos)

   → Matrix.por2.srt
      → Matrix.por.srt
   → Matrix.Extras.por2.srt
      → Matrix.Extras.por.srt

2. Adicionar .por.srt a legendas sem idioma (1 arquivos)

   → Commentary.srt
      → Commentary.por.srt

3. Remover arquivos indesejados (8 arquivos)

   ✗ 3 arquivo(s) .eng.srt
   ✗ 3 arquivo(s) .spa.srt
   ✗ 2 arquivo(s) .jpg

════════════════════════════════════════════════════════════════════════
📊 RESUMO:

  Arquivos .por2.srt a renomear:      2
  Legendas sem idioma a renomear:     1
  Arquivos a remover:                 8
  Diretórios a remover:               0
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Total de operações:                 11

════════════════════════════════════════════════════════════════════════

Deseja executar estas operações? [s/N]:
```

## 🛠️ Opções Completas

### Opções Gerais
| Opção | Descrição |
|-------|-----------|
| `-h, --help` | Exibe ajuda completa |
| `-v, --version` | Exibe versão |
| `-d, --dry-run` | Preview (não executa) |
| `-y, --yes` | Pula confirmações |
| `-i, --interactive` | Modo interativo (padrão) |
| `-q, --quiet` | Modo silencioso |
| `-V, --verbose` | Modo verboso |
| `-w, --workdir DIR` | Define diretório de trabalho |

### Controle de Operações
| Opção | Descrição |
|-------|-----------|
| `--no-rename-por2` | Desabilita renomeação .por2.srt |
| `--no-rename-no-lang` | Desabilita renomeação sem idioma |
| `--no-remove-unwanted` | Desabilita remoção de indesejados |
| `--no-remove-metadata` | Desabilita remoção de metadata |
| `--only-rename-por2` | Apenas renomeia .por2.srt |
| `--only-rename-no-lang` | Apenas renomeia sem idioma |
| `--only-remove-unwanted` | Apenas remove indesejados |
| `--only-remove-metadata` | Apenas remove metadata |

### Opções Avançadas
| Opção | Descrição |
|-------|-----------|
| `-b, --backup DIR` | Cria backup antes |
| `-l, --log FILE` | Salva log em arquivo |
| `--min-pt-words N` | Mínimo de palavras PT (padrão: 5) |

## 🧠 Detecção de Português

O script usa algoritmo inteligente para detectar legendas em português:

1. Lê as primeiras 100 linhas do arquivo
2. Procura por 33 palavras comuns em português
3. Se encontrar ≥ 5 palavras (configurável), marca como PT
4. Apenas legendas identificadas como PT são renomeadas

### Palavras Verificadas
```
que, não, para, com, uma, mais, muito, está, você, seu, sua,
ele, ela, são, mas, por, até, também, bem, foi, ser, vai,
pode, ainda, onde, quando, como, porque, sem, sobre, todo,
tinha, foram, fazer
```

### Ajustar Sensibilidade
```bash
# Mais flexível (aceita com apenas 3 palavras)
manager-srt --min-pt-words 3

# Mais rigoroso (exige 10 palavras)
manager-srt --min-pt-words 10
```

## 🌍 Idiomas Removidos

O script remove legendas em 40+ idiomas:

```
ara (árabe), eng (inglês), spa (espanhol), fre (francês),
ger (alemão), ita (italiano), rus (russo), chi (chinês),
jpn (japonês), kor (coreano), pol (polonês), dut (holandês),
swe (sueco), dan (dinamarquês), nor (norueguês), fin (finlandês),
tur (turco), gre (grego), heb (hebraico), hrv (croata),
hun (húngaro), ind (indonésio), may (malaio), nob (norueguês bokmål),
rum (romeno), tha (tailandês), ukr (ucraniano), vie (vietnamita),
hin (hindu), tam (tâmil), tel (telugu), slo (eslovaco),
bul (búlgaro), lav (letão), lit (lituano), slv (esloveno),
glg (galego), cat (catalão), baq (basco), cze (tcheco),
fil (filipino)

+ Variações: eng2, spa2, etc
```

## 📊 Estrutura do Projeto

```
manager-srt/
├── manager-srt           # Script principal
├── README.md             # Este arquivo
├── MELHORIAS.md          # Documentação de melhorias v2 → v3
├── EXEMPLOS.sh           # Scripts de exemplo
├── CHEATSHEET.txt        # Referência rápida
└── LICENSE               # Licença MIT
```

## 🔧 Requisitos

- **Bash** 4.0 ou superior
- **Comandos Unix padrão**: find, grep, mv, rm, head
- **Opcional**: inotify-tools (para modo watch)

Funciona em:
- ✅ Linux (todas as distribuições)
- ✅ macOS (com Bash 4+)
- ✅ WSL (Windows Subsystem for Linux)

## 🤝 Contribuindo

Contribuições são bem-vindas! Por favor:

1. Fork o projeto
2. Crie uma branch para sua feature (`git checkout -b feature/MinhaFeature`)
3. Commit suas mudanças (`git commit -am 'Adiciona MinhaFeature'`)
4. Push para a branch (`git push origin feature/MinhaFeature`)
5. Abra um Pull Request

## 📝 Changelog

### v1.0.4 (2024-11-26)
- ✨ Sistema `--help` completo e colorido
- ✨ Modo preview/dry-run detalhado
- ✨ 20+ opções de linha de comando
- ✨ Controle granular de operações
- ✨ Backup automático opcional
- ✨ Sistema de logs completo
- ✨ Múltiplos modos de execução
- ✨ Trabalhar em qualquer diretório
- ✨ Detecção melhorada de português
- ✨ Interface visual aprimorada
- ✨ Tratamento robusto de erros

### v2.0.0 (2024-11-20)
- Script funcional básico
- Operações principais implementadas
- Interface colorida simples

## 🐛 Reportar Bugs

Encontrou um bug? Por favor abra uma [issue](https://github.com/talesam/manager-srt/issues) com:

- Versão do script (`manager-srt --version`)
- Sistema operacional
- Comando executado
- Output do erro
- Comportamento esperado

## 📄 Licença

Este projeto está licenciado sob a **MIT License** - veja o arquivo [LICENSE](LICENSE) para detalhes.

## 🎯 Roadmap

Funcionalidades planejadas para futuras versões:

- [ ] Arquivo de configuração (~/.manager-srt.conf)
- [ ] Filtros customizáveis via CLI
- [ ] Sistema de undo/rollback
- [ ] Relatórios em HTML
- [ ] Integração com notificações
- [ ] Suporte a múltiplos idiomas no mesmo dir
- [ ] Modo de verificação sem alteração
- [ ] Modo daemon/watch
- [ ] GUI opcional (zenity/dialog)
- [ ] Suporte a plugins

## 💡 FAQ

**P: O script é seguro?**  
R: Sim! Use `--dry-run` para ver exatamente o que será feito. Use `--backup` para proteção extra.

**P: Posso usar em produção?**  
R: Sim! O script é estável e testado. Recomendamos usar com `--backup` e `--log`.

**P: Funciona com outros idiomas?**  
R: Atualmente otimizado para português, mas você pode adaptar o código facilmente.

**P: Por que Bash e não Python/Ruby?**  
R: Zero dependências externas. Funciona em qualquer sistema Unix-like out of the box.

**P: E se eu quiser manter alguns idiomas?**  
R: Use `--only-rename-por2` e `--only-rename-no-lang` para não remover nada.

---

<div align="center">

**Se este projeto foi útil, considere deixar uma ⭐ no GitHub!**

[Reportar Bug](https://github.com/talesam/manager-srt/issues) •
[Solicitar Feature](https://github.com/talesam/manager-srt/issues) •
[Documentação](https://github.com/talesam/manager-srt/wiki)

</div>
