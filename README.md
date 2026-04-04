# myagent

> **Claude düşünür ve konuşur. Gemini çalışır. Sen sadece ne istediğini söylersin.**

`myagent`, iki yapay zeka modelinin güçlerini bilinçli bir maliyet asimetrisiyle birleştiren terminal tabanlı çok-ajanlı bir CLI aracıdır.

**Temel fikir:**
- **Claude** — mükemmel planlama, review ve doğal dil anlama. Token kotası var, dikkatli kullan.
- **Gemini** — sınırsız ücretsiz token. Ağır işi yap: tüm kodu yaz, tüm dosyaları oluştur.
- **Sonuç** — bir Claude Code oturumuna kıyasla çok daha az Claude token harcarken karmaşık projeler üretir.

```
myagent> web scraper yaz, test ekle

  ⊛ Claude planlıyor…
    STEP 1: Create scraper.py with requests + BeautifulSoup...
    STEP 2: Write scrape_page(url) function...
  ⊛ Gemini yürütüyor — 5 adım…
    FILE: scraper.py
    FILE: test_scraper.py
  ⊛ Review — Claude analiz ediyor…
    ✓ Review onaylandı (tur 1)
  ⊛ Claude tamamlanma doğruluyor…
    ✓ Tamamlama doğrulandı

myagent> bu kodu açıklar mısın?

  ⊛ Claude düşünüyor…
  ╭──────────────────────────────────────╮
  │ scraper.py, BeautifulSoup kullanarak │
  │ HTML'yi parse eder...                │
  ╰──────────────────────────────────────╯
```

---

## Mimari: Neden İki Model?

Çoğu ajan sistemi aynı modeli tekrarlı çağırır. Bu proje bilinçli asimetri kurar:

| | Claude | Gemini |
|---|---|---|
| **Güç** | Derin akıl yürütme, planlama, review | Geniş kapasite, hızlı kod üretimi |
| **Limit** | Token kotası hızla dolar | Claude kadar derin düşünemez |
| **Rolü** | Brain — az çağrılır | Muscle — çok çalışır |
| **Çağrı sayısı** | 3-5 (plan + review + verify) | 1-2 (execute + fix) |

**Bir görev için tipik akış:**
```
Kullanıcı girdisi
    │
    ▼
Chat (Claude) — soru mu görev mi?
    │                    │
    ▼ (görev)            ▼ (soru)
Planner (Claude)     Doğrudan yanıt
    │
    ▼
Worker (Gemini) — toplu yürütme
    │
    ▼
Reviewer (Claude) — ruff + test + fix
    │
    ▼
Completer (Claude) — eksik var mı?
    │
    ▼
Bitti
```

---

## Tam Pipeline

### 1. Chat (Konuşma Katmanı)

Her kullanıcı girdisi önce `Chat` modülüne gelir. Claude iki şeyden birini yapar:

- **Soru / açıklama isteği** → doğrudan markdown yanıt döner, session geçmişi korunur
- **Görev** → görevi İngilizce task tanımına dönüştürür, pipeline'a iletir

Konuşma geçmişi session boyunca tutulur (son 10 tur). Önceki projeleri, oluşturulan dosyaları, tamamlanan görevleri hatırlar.

### 2. Planner (Claude)

Claude, görevi 3-10 atomik adıma böler. Workspace'teki mevcut dosyaları, AST sembol haritasını ve geçmiş görev bağlamını da görür — zaten var olan kodu yeniden yazmaz.

```
STEP 1: Create calculator.py with add(), subtract(), multiply(), divide()
STEP 2: Write test_calculator.py with pytest assertions
STEP 3: Run pytest to verify tests pass
```

### 3. Worker (Gemini)

Tüm adımlar tek bir toplu çağrıda Gemini'ye gönderilir. Her adım `===END===` ile ayrılmış `FILE:` veya `BASH:` bloğu döner.

```
FILE: calculator.py
def add(a, b): return a + b
...
===END===
FILE: test_calculator.py
import pytest
...
===END===
BASH: python -m pytest test_calculator.py -v
===END===
```

### 4. Review Döngüsü (Claude)

Dosyalar oluşturulduktan sonra Claude kodu inceler:
- `ruff` ile lint kontrolü (otomatik `--fix` uygulanır)
- `pytest` varsa testleri çalıştırır
- Hata varsa Gemini'ye düzeltme adımları gönderir
- Maksimum 2 tur, kısır döngü tespiti var

### 5. Completion Verification (Claude)

Claude oluşturulan dosyaları okur ve asıl görevle karşılaştırır:
- `COMPLETE` → bitti
- `INCOMPLETE + STEP 1: ...` → Gemini'ye eksik adımlar gönderilir, tekrar doğrulanır

### 6. Persistent Memory

Her görev `.myagent/history.jsonl`'e kaydedilir. Bir sonraki görevde Claude bu geçmişi görür:

```
Past tasks:
1. [2026-04-15] "fibonacci web app" → fibonacci.py, app.py, index.html
2. [2026-04-16] "calculator with tests" → calculator.py, test_calculator.py
```

---

## Kurulum

### Gereksinimler

- Python 3.10+
- **Claude için:** `ANTHROPIC_API_KEY` **veya** `claude` CLI (Claude Code OAuth)
- **Gemini için:** `GEMINI_API_KEY` **veya** `gemini` CLI (Gemini CLI OAuth)

### Adımlar

```bash
git clone https://github.com/kullanici/myagent.git
cd myagent

# uv (önerilir)
uv venv .venv && source .venv/bin/activate
uv pip install -e .

# pip ile de çalışır
python -m venv .venv && source .venv/bin/activate
pip install -e .

myagent    # ilk çalıştırmada kurulum sihirbazı başlar
```

### Docker (önerilir)

```bash
cd myagent
./run.sh                     # interactive REPL
./run.sh "port scanner yaz"  # one-shot görev
./run.sh --build             # image'ı yeniden oluştur
./run.sh --shell             # container içine bash
```

Docker ile `~/.gemini`, `~/.claude`, `~/.claude.json` otomatik mount edilir — API key gerekmez.

---

## Auth Sistemi

| Mod | Claude | Gemini |
|---|---|---|
| **api** | `ANTHROPIC_API_KEY` | `GEMINI_API_KEY` / `GOOGLE_API_KEY` |
| **cli** | `claude` komutu (Claude Code OAuth) | `gemini` komutu (Gemini CLI OAuth) |

**Önerilen yapılandırma** — API key gerektirmez:

```json
{
  "claude_mode": "cli",
  "claude_model": "claude-sonnet-4-6",
  "gemini_mode": "cli",
  "gemini_model": "gemini-2.5-flash"
}
```

```bash
myagent --setup    # yapılandırma sihirbazı
```

---

## Model Seçimi

### Claude (Planner / Reviewer / Chat)

| Alias | Model ID | Kullanım |
|---|---|---|
| `opus` | `claude-opus-4-6` | Karmaşık, çok adımlı projeler |
| `sonnet` | `claude-sonnet-4-6` | Genel amaçlı, dengeli (önerilir) |
| `haiku` | `claude-haiku-4-5-20251001` | Hızlı, basit görevler |

### Gemini (Worker)

| Alias | Model ID | Kullanım |
|---|---|---|
| `2.5-flash` | `gemini-2.5-flash` | Genel amaçlı kod üretimi (önerilir) |
| `2.5-pro` | `gemini-2.5-pro` | Karmaşık mimari, gelişmiş akıl yürütme |
| `flash` | `gemini-2.0-flash` | Hızlı fallback |

---

## Kullanım

### İnteraktif REPL

```bash
$ myagent
╔══════════════════════════════════════════╗
║           myagent  v1.0.0                ║
║  Claude plans · Gemini executes          ║
╚══════════════════════════════════════════╝

myagent> basit bir şifre üreteci yaz
myagent> buna GUI ekle
myagent> az önce yazdığın kodu açıkla
myagent> fibonacci nedir, nasıl çalışır?
myagent> düzelt
```

Herhangi bir şey yazabilirsin — Claude soru mu görev mi olduğuna karar verir.

### One-shot Mod

```bash
myagent "basit bir HTTP sunucusu yaz"
myagent "create a markdown to HTML converter" --verbose
myagent "port scanner yaz" --dry-run
myagent "web scraper yaz" --gemini-model 2.5-pro
```

### REPL Komutları

| Komut | Açıklama |
|---|---|
| `<herhangi bir şey>` | Chat üzerinden yönlendirilir (soru veya görev) |
| `run <görev>` | Chat'i atlayarak doğrudan pipeline'a gönder |
| `devam` / `devam et` | Son projeye devam et |
| `düzelt` / `fix` | Son projede hataları düzelt |
| `test ekle` | Son projeye test yaz |
| `geçmiş` / `history` | Geçmiş görevleri göster |
| `son` / `last` | Son görevin detayları |
| `dosyalar` / `ls` | Çalışma dizinindeki dosyalar |
| `temizle` | Çalışma dizinini temizle |
| `setup` | Auth ve model ayarlarını yeniden yapılandır |
| `models` | Mevcut modelleri listele |
| `config` | Mevcut yapılandırmayı göster |
| `help` | Yardım |
| `exit` | Çıkış |

### CLI Bayrakları

```bash
myagent [GÖREV] [SEÇENEKLER]
```

| Bayrak | Açıklama |
|---|---|
| `--claude-model MODEL` | Claude modeli (alias veya tam ID) |
| `--gemini-model MODEL` | Gemini modeli (alias veya tam ID) |
| `--claude-mode api\|cli` | Claude auth modunu geçersiz kıl |
| `--gemini-mode api\|cli` | Gemini auth modunu geçersiz kıl |
| `--dry-run` | Sadece planı göster, yürütme |
| `--sequential` | Adımları tek tek yürüt (varsayılan: toplu) |
| `--no-review` | Review döngüsünü atla |
| `--no-complete` | Completion verification'ı atla |
| `--max-review-rounds N` | Max review turu (varsayılan: 2) |
| `--max-completion-rounds N` | Max completion turu (varsayılan: 2) |
| `--clarify` | Görev öncesi Claude'a netleştirme soruları sor |
| `--auto-deps` | Eksik Python paketleri otomatik kur |
| `--work-dir PATH` | Dosya yazma dizini |
| `--max-steps N` | Maksimum plan adımı (varsayılan: 10) |
| `--verbose` / `-v` | Ham model çıktısını göster |
| `--list-models` | Mevcut modelleri listele ve çık |
| `--config` | Yapılandırmayı göster ve çık |
| `--setup` | Kurulum sihirbazını çalıştır |

---

## Proje Yapısı

```
myagent/
├── myagent/
│   ├── cli.py                  — REPL + argparse + SessionState
│   ├── ui.py                   — Rich terminal UI (streaming, paneller)
│   ├── models.py               — model kayıt defteri, alias çözümü
│   ├── setup_wizard.py         — kurulum ve yeniden yapılandırma
│   │
│   ├── agent/
│   │   ├── chat.py             — konuşma katmanı: soru↔görev routing
│   │   ├── planner.py          — Claude → STEP listesi
│   │   ├── worker.py           — Gemini → FILE/BASH toplu çıktısı
│   │   ├── executor.py         — dosya yazımı + güvenli komut yürütme
│   │   ├── reviewer.py         — ruff + pytest + Claude fix döngüsü
│   │   ├── completer.py        — Claude tamamlama doğrulayıcı
│   │   ├── clarifier.py        — görev öncesi netleştirme soruları
│   │   ├── deps.py             — eksik pip paketlerini tespit ve kur
│   │   └── pipeline.py         — tam döngü orkestrasyonu
│   │
│   ├── memory/
│   │   └── history.py          — kalıcı görev geçmişi (jsonl + file index)
│   │
│   ├── i18n/
│   │   ├── translator.py       — TR↔EN sözlük (API çağrısı yok)
│   │   └── locale.py           — sistem dili tespiti
│   │
│   ├── prompts/
│   │   ├── planner.txt         — Claude planner sistem promptu
│   │   ├── worker.txt          — Gemini worker sistem promptu
│   │   ├── worker_batch.txt    — Gemini toplu yürütme promptu
│   │   └── clarifier.txt       — Claude clarifier sistem promptu
│   │
│   └── config/
│       ├── settings.py         — sabitler, validate()
│       └── auth.py             — mod/model tespiti, override, config I/O
│
├── docker-compose.yml
├── Dockerfile
└── run.sh
```

---

## Güvenlik Modeli

### Path Traversal Koruması

```python
target = (WORK_DIR / filename).resolve()
target.relative_to(WORK_DIR.resolve())   # ValueError → reddedilir
```

`../../etc/passwd` ve tüm dizin geçiş girişimleri reddedilir.

### İzin Listesi (non-Docker)

```python
ALLOWED_COMMANDS = frozenset({"mkdir", "touch", "echo", "cat"})
```

Docker içinde (`MYAGENT_DOCKER=1`) whitelist devre dışı kalır — container sandbox yeterli koruma sağlar.

### `shell=True` Yasağı

Tüm komutlar `shlex.split()` ile ayrıştırılır, `subprocess.run(list)` ile çalıştırılır. `eval()` ve `exec()` hiçbir yerde kullanılmaz.

---

## Yapılandırma

`~/.myagent/config.json`:

```json
{
  "claude_mode": "cli",
  "claude_model": "claude-sonnet-4-6",
  "gemini_mode": "cli",
  "gemini_model": "gemini-2.5-flash"
}
```

Ortam değişkenleri:

| Değişken | Açıklama |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API anahtarı (api modu) |
| `GEMINI_API_KEY` | Gemini API anahtarı (api modu) |
| `MYAGENT_WORK_DIR` | Dosya yazma dizini (varsayılan: `./workspace`) |
| `MYAGENT_DOCKER` | `1` ise komut whitelist'i devre dışı |

---

## Benzer Projeler

| Proje | Fark |
|---|---|
| **MetaGPT** | Çok ajanlı ama aynı model ailesi |
| **AutoGen** | Ajan konuşmaları ama homojen modeller |
| **CrewAI** | Rol bazlı ama maliyet asimetrisi optimizasyonu yok |
| **LangGraph** | Bu tür sistemler için framework, sistem değil |

**myagent'ın farkı:** "Pahalı+akıllı model sadece manager, ücretsiz+hızlı model worker" şeklinde bilinçli maliyet asimetrisi. Konuşma geçmişi, proje hafızası ve tam agentic döngüyle.

---

## Roadmap

- [x] Toplu yürütme — tüm adımlar tek Gemini çağrısında
- [x] CLI auth — API key gerektirmez
- [x] Türkçe/İngilizce input — çeviri API çağrısı olmadan
- [x] Model seçimi ve alias sistemi
- [x] Rich streaming UI — model çıktısı anlık görünür
- [x] Review döngüsü — ruff + pytest + Claude fix loop
- [x] Completion verification — Claude eksik olanı tespit eder, Gemini tamamlar
- [x] Persistent memory — görev ve dosya geçmişi kalıcı kaydedilir
- [x] Session state — "bunu geliştir", "düzelt" gibi doğal referanslar
- [x] Conversational mode — soru sormak için ayrı komut gerekmez
- [x] Docker desteği — izole sandbox
- [x] Dependency management — eksik paket otomatik tespit
- [ ] Paralel adım yürütme (bağımsız adımlar aynı anda)
- [ ] Token kullanım ölçümü — Claude Code vs myagent karşılaştırması
- [ ] Web UI (opsiyonel)

---

## Lisans

MIT
