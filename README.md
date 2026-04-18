
<div align="center">

<img src="banner.svg" alt="myAgent" width="672"/>

### Claude düşünür — Gemini çalışır — Sen sadece ne istediğini söylersin

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Claude](https://img.shields.io/badge/Planner-Claude-D97706?style=flat-square)
![Gemini](https://img.shields.io/badge/Worker-Gemini-4285F4?style=flat-square)
![Textual](https://img.shields.io/badge/TUI-Textual-6D28D9?style=flat-square)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)

</div>

---

## Fikir

Çoğu AI ajanı aynı modeli tekrar tekrar çağırır. myAgent farklı bir yaklaşım benimser: **bilinçli asimetri.**

> Pahalı modeli sadece beyne ver. Bedava modeli kola.

Claude Code ile aynı işi yaparken token harcamanın onda birine çalışırsın — Claude yalnızca planlar ve inceler, Gemini tüm ağır işi ücretsiz olarak yürütür.

---

## Mimari

```
╔══════════════════════════════════════════════════════════════════╗
║                        myAgent Pipeline                          ║
╚══════════════════════════════════════════════════════════════════╝

  Sen                                                          Sen
  │                                                             ▲
  │  "basit bir şifre üreteci yaz"                              │
  ▼                                                             │
┌─────────────────────────────────┐                   ┌─────────────────┐
│   Chat Router  (Claude)         │──── Soru ─────────▶  Markdown cevap │
│                                 │                   └─────────────────┘
│   Görev mi? → Pipeline başlat   │
└──────────────┬──────────────────┘
               │  Görev
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Planner  (Claude)                                               │
│                                                                  │
│  STEP 1: Create password_gen.py with generate(length, symbols)   │
│  STEP 2: Add CLI argparse interface                              │
│  STEP 3: Run python password_gen.py --test                       │
└──────────────┬───────────────────────────────────────────────────┘
               │  Plan
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Worker  (Gemini)                                                │
│                                                                  │
│  FILE: password_gen.py  ···  BASH: python password_gen.py        │
│  Tüm adımlar tek çağrıda — ücretsiz, hızlı, paralel              │
└──────────────┬───────────────────────────────────────────────────┘
               │  Dosyalar + çıktı
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Reviewer  (Claude)                                              │
│                                                                  │
│  ruff lint → pytest → "LGTM" veya "Şunu düzelt: …"               │
│  Hata varsa Gemini'ye düzeltme gönderilir  (maks 2 tur)          │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Verifier  (Claude)                                              │
│                                                                  │
│  "COMPLETE" → bitti    "INCOMPLETE: STEP 2" → tekrar döngü       │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
         /workspace  ✓
```

---

## Özellikler

```
                          myAgent
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
       Arayüz            Pipeline           Güvenlik
          │                  │                  │
    ┌─────┴─────┐      ┌─────┴─────┐      ┌─────┴─────┐
    │           │      │           │      │           │
   TUI        REPL  Çift Model  Hafıza  Sandbox    Path Guard
    │                  │           │
  Slash             Claude +    JSON
 Komutları         Gemini     Geçmişi
    │
  /auth
  /model
  /export
  /compact
  ...
```

| | Özellik | Açıklama |
|---|---|---|
| **Arayüz** | TUI modu | Tam ekran Textual — `/` ile komut otomatik tamamlama |
| | REPL modu | Klasik terminal, aynı güç |
| | One-shot | `myagent "görev"` tek satırda çalışır |
| **Pipeline** | Çift model | Claude planlar + inceler, Gemini yürütür |
| | Review döngüsü | ruff + pytest + Claude otomatik düzeltme |
| | Completion verify | Görev tamamlanmadan pipeline kapanmaz |
| **Hafıza** | Session kalıcılığı | Oturumlar JSON'a kaydedilir, isimlendirilir |
| | Görev geçmişi | "bunu düzelt", "test ekle" doğal çalışır |
| **Teknik** | Canlı reflow | Terminal resize olunca içerik anında yeniden düzenlenir |
| | Auth esnekliği | API key veya OAuth (Claude Code / Gemini CLI) |
| | Docker sandbox | Tam izole çalışma ortamı |

---

## Kurulum

### Gereksinimler

| Gereksinim | Açıklama |
|---|---|
| Python 3.10+ | |
| **Claude için** | `ANTHROPIC_API_KEY` **ya da** Claude Code CLI (`claude login`) |
| **Gemini için** | `GEMINI_API_KEY` **ya da** Gemini CLI (`gemini login`) |

> Claude Code aboneliğin (Pro/Max) varsa API key gerekmez — myAgent direkt kullanır.

---

### Seçenek A — Python venv

```bash
git clone https://github.com/Mustafkgl/myAgent.git
cd myAgent

# uv (önerilir)
uv venv .venv && source .venv/bin/activate && uv pip install -e .

# ya da pip
python -m venv .venv && source .venv/bin/activate && pip install -e .

# başlat
python -m myagent --tui     # TUI modu
python -m myagent           # REPL modu
```

### Seçenek B — Docker (önerilir)

`~/.claude`, `~/.gemini`, `~/.myagent` otomatik mount edilir. Hiçbir şeyi elle yapılandırmak gerekmez.

```bash
cd myAgent

docker compose build              # image oluştur
docker compose run --rm myagent   # başlat
```

```bash
./run.sh                          # interaktif REPL
./run.sh "port scanner yaz"       # tek seferlik görev
./run.sh --build                  # rebuild + başlat
./run.sh --shell                  # container bash'ine gir
```

### İlk Çalıştırma

İlk açılışta kurulum sihirbazı çalışır — hangi auth modunu ve hangi modelleri kullanacağını sorar. Sonradan TUI içinden `/auth` ve `/model` ile değiştirilebilir.

---

## TUI Modu

```
  ┌─────────────────────────────────────────────────────────┐
  │  myAgent                               12:34:56  Cmt    │
  ├─────────────────────────────────────────────────────────┤
  │                                                         │
  │                          █████████                       │
  │                         ███░░░░░███                      │
  │  ████  ████  ████  ████ ░███    ░███  ████  ████  ████       │
  │  ░░██  ░░██  ░░██  ░░██ ░███████████ ░░██  ░░██  ░░██      │
  │   ░░    ░░    ░░    ░░  ░███░░░░░███  ░░    ░░    ░░     │
  │                         ░███    ░███                     │
  │  v1.0.0 · Claude planlar · Gemini yürütür               │
  │  claude-sonnet-4-6  /  gemini-2.5-flash                 │
  │                                                         │
  │  ↑↓ geçmiş · Tab tamamla · Ctrl+Y kopyala · F1 yardım   │
  │                                                         │
  ├─────────────────────────────────────────────────────────┤
  │ ❯  Ne yapmamı istersin?                                 │
  └─────────────────────────────────────────────────────────┘
```

### Klavye Kısayolları

| Kısayol | Açıklama |
|---|---|
| `↑` / `↓` | Girdi geçmişinde gez |
| `Tab` | Slash komutunu otomatik tamamla |
| `Ctrl+Y` | Son AI cevabını panoya kopyala |
| `Ctrl+L` | Ekranı temizle |
| `F1` | Yardım |
| `Ctrl+C` | İlk basış uyarı verir, ikinci basış çıkış |
| `Esc` | Açık ekranı kapat |

### Slash Komutları

`/` yazmaya başlayınca altta otomatik tamamlama açılır — `↑` `↓` ile seç, `Enter` ile uygula.

| Komut | Açıklama |
|---|---|
| `/help` | Tüm komutları ve kısayolları göster |
| `/auth` | Kimlik doğrulama ekranı |
| `/model` | Model seçim ekranı |
| `/config` | Mevcut yapılandırmayı göster |
| `/status` | Oturum istatistikleri |
| `/about` | Versiyon ve model bilgileri |
| `/think` | Verbose modunu aç / kapat |
| `/theme dark\|light` | Temayı değiştir |
| `/sessions` | Kayıtlı oturumları listele |
| `/load <n>` | Oturum yükle |
| `/rename <ad>` | Oturumu yeniden adlandır |
| `/new` | Yeni oturum başlat |
| `/export` | Oturumu Markdown dosyasına aktar |
| `/compact` | Konuşma geçmişini özetleyip sıkıştır |
| `/editor` | `$EDITOR` aç — çok satırlı giriş |
| `/clear` | Ekranı temizle |
| `/exit` | Çıkış |

---

### /auth Ekranı

```
╔══════════════════════════════════════════════════════════════╗
║  Kimlik Doğrulama & Bağlantı Ayarları                        ║
║  ↑ ↓ seçenek değiştir  ·  Tab sonraki bölüm                  ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  PLANLAYAN — Claude                                          ║
║    ○ API Anahtarı       ~3 s/plan  · pay-as-you-go           ║
║    ● Claude Code CLI    ~5 s/plan  · abonelik (Pro/Max)      ║
║                                                              ║
║    ✓ Claude Code kurulu ve giriş yapılmış                    ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  ÇALIŞAN — Worker                                            ║
║    ● Gemini API         ~2 s/adım  · hızlı                   ║
║    ○ Claude Code        ~5 s/adım  · aynı abonelik           ║
║    ○ Gemini CLI         ~40 s/adım · Node.js CLI             ║
║                                                              ║
║                  [  Kaydet ve Devam Et  ]                    ║
╚══════════════════════════════════════════════════════════════╝
```

### /model Ekranı

```
╔══════════════════════════════════════════════════════════════╗
║  Model Seçimi                                                ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  PLANLAYAN — Claude                                          ║
║    ● claude-opus-4-7    ★  (mevcut)  — Most capable          ║
║    ○ claude-sonnet-4-6              — Balanced speed         ║
║    ○ claude-haiku-4-5               — Fast and lightweight   ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  ÇALIŞAN — Gemini                                            ║
║    ● gemini-2.5-flash   ★  (mevcut)  — Fast + reasoning      ║
║    ○ gemini-2.5-pro                  — Most capable          ║
║    ○ gemini-2.0-flash                — Stable fallback       ║
║                                                              ║
║                  [  Kaydet ve Devam Et  ]                    ║
╚══════════════════════════════════════════════════════════════╝
```

`★` önerilen modeli gösterir. API key varsa canlı model listesi çekilir.

---

## REPL Modu

```bash
python -m myagent
```

```
myagent> basit bir şifre üreteci yaz
myagent> buna GUI ekle
myagent> az önce yazdığın kodu açıkla
myagent> fibonacci nedir?
myagent> düzelt
myagent> test ekle
```

Claude her girdiyi otomatik değerlendirir: **soru mu → cevap**, **görev mi → pipeline**.

| Komut | Açıklama |
|---|---|
| `devam` | Son projeye kaldığın yerden devam et |
| `düzelt` / `fix` | Son projede hataları düzelt |
| `test ekle` | Son projeye testler ekle |
| `geçmiş` | Tüm geçmiş görevleri göster |
| `dosyalar` / `ls` | Workspace'deki dosyaları listele |
| `run <görev>` | Chat'i atlayıp doğrudan pipeline'a gönder |
| `help` | Yardım |
| `exit` | Çıkış |

---

## One-shot Mod

```bash
# Temel kullanım
python -m myagent "REST API yaz, endpoint'leri test et"

# Seçenekler
python -m myagent "veri analizi yap"  --claude-model opus  --gemini-model 2.5-pro
python -m myagent "web scraper yaz"   --dry-run            # planı göster, çalıştırma
python -m myagent "büyük proje"       --clarify            # önce sorular sor
python -m myagent "şifreleme kütüphanesi" --verbose        # ham model çıktısı
```

---

## CLI Referansı

```
python -m myagent [GÖREV] [SEÇENEKLER]
```

| Seçenek | Açıklama |
|---|---|
| `--tui` | Textual TUI modunda başlat |
| `--claude-model MODEL` | Claude modeli — alias veya tam ID |
| `--gemini-model MODEL` | Gemini modeli — alias veya tam ID |
| `--work-dir PATH` | Dosya yazma dizini |
| `--max-steps N` | Maksimum plan adımı (varsayılan: 10) |
| `--dry-run` | Planı göster, yürütme |
| `--no-review` | Review döngüsünü atla |
| `--clarify` | Başlamadan önce netleştirme soruları sor |
| `--verbose` / `-v` | Ham model çıktısını göster |
| `--setup` | Kurulum sihirbazını çalıştır |
| `--list-models` | Mevcut modelleri listele |
| `--version` | Versiyon bilgisi |

**Model alias'ları:**

| Alias | Model |
|---|---|
| `opus` | `claude-opus-4-7` |
| `sonnet` | `claude-sonnet-4-6` |
| `haiku` | `claude-haiku-4-5-20251001` |
| `2.5-flash` | `gemini-2.5-flash` |
| `2.5-pro` | `gemini-2.5-pro` |
| `flash` | `gemini-2.0-flash` |

---

## Auth Yapılandırması

```
~/.myagent/config.json
```

```json
{
  "claude_mode":  "cli",
  "claude_model": "claude-sonnet-4-6",
  "gemini_mode":  "api",
  "gemini_model": "gemini-2.5-flash"
}
```

| Sağlayıcı | Mod | Gereksinim |
|---|---|---|
| Claude | `api` | `ANTHROPIC_API_KEY` |
| Claude | `cli` | `claude` CLI + `claude login` |
| Gemini | `api` | `GEMINI_API_KEY` |
| Gemini | `cli` | `gemini` CLI + `gemini login` |

```bash
# Claude Code yoksa kur
curl -fsSL https://claude.ai/install.sh | sh && claude login

# Gemini CLI yoksa kur
npm install -g @google/gemini-cli && gemini login
```

---

## Proje Yapısı

```
myagent/
├── myagent/
│   ├── cli.py              ← REPL, argparse, SessionState
│   ├── tui.py              ← Textual TUI, slash komutları
│   ├── auth_screen.py      ← /auth ekranı
│   ├── model_screen.py     ← /model ekranı
│   ├── ui.py               ← Rich terminal (streaming, Live)
│   ├── interrupt.py        ← ESC / Ctrl+C yönetimi
│   ├── models.py           ← model kayıt defteri, canlı keşif
│   ├── setup_wizard.py     ← ilk çalıştırma sihirbazı
│   │
│   ├── agent/
│   │   ├── pipeline.py     ← tam döngü orkestrasyonu
│   │   ├── chat.py         ← soru ↔ görev yönlendirme
│   │   ├── planner.py      ← Claude → STEP listesi
│   │   ├── worker.py       ← Gemini → FILE/BASH çıktısı
│   │   ├── executor.py     ← güvenli dosya yazımı + komut
│   │   ├── reviewer.py     ← ruff + pytest + düzeltme döngüsü
│   │   ├── completer.py    ← tamamlama doğrulayıcı
│   │   └── deps.py         ← eksik pip paket tespiti
│   │
│   ├── memory/
│   │   └── history.py      ← kalıcı görev geçmişi (jsonl)
│   │
│   └── config/
│       ├── settings.py     ← sabitler, validate()
│       └── auth.py         ← mod/model tespiti, config I/O
│
├── docker-compose.yml
├── Dockerfile
└── run.sh
```

---

## Yapılandırma Dosyaları

| Dosya | İçerik |
|---|---|
| `~/.myagent/config.json` | Mod ve model tercihleri |
| `~/.myagent/.env` | API key'ler (TUI'den /auth ile kaydedilir) |
| `~/.myagent/sessions/*.json` | TUI oturum geçmişi |
| `~/.myagent/history.jsonl` | Görev geçmişi |

| Ortam Değişkeni | Açıklama |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API anahtarı |
| `GEMINI_API_KEY` | Gemini API anahtarı |
| `MYAGENT_WORK_DIR` | Dosya yazma dizini (varsayılan: `./workspace`) |
| `MYAGENT_DOCKER` | `1` ise komut whitelist devre dışı |

---

## Güvenlik

- **Path traversal koruması** — tüm dosya yazma işlemleri `WORK_DIR` içinde kontrol edilir; `../../etc/passwd` gibi denemeler reddedilir
- **`shell=False`** — her komut `shlex.split()` ile liste olarak çalışır, injection mümkün değil
- **`eval()` / `exec()` yok** — hiçbir yerde kullanılmaz
- **Docker sandbox** — `MYAGENT_DOCKER=1` ile tam izolasyon

<div align="center">

---

*Claude düşünür. Gemini çalışır.*

</div>
