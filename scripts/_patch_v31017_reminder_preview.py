from pathlib import Path

# Validation retry after aligning the non-sending safety wording.
ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "liturgie_app.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: attendu 1 occurrence, trouvé {count}")
    return text.replace(old, new, 1)


text = PATH.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''from whatsapp_readiness import (
    display_rows as whatsapp_display_rows,
    future_readiness_rows,
    readiness_summary,
)
''',
    '''from whatsapp_readiness import (
    display_rows as whatsapp_display_rows,
    future_readiness_rows,
    readiness_summary,
)
from whatsapp_reminder_preview import (
    display_rows as reminder_preview_display_rows,
    preview_rows as reminder_preview_rows,
    preview_summary as reminder_preview_summary,
)
''',
    "imports aperçu rappels",
)

text = replace_once(
    text,
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.16-weekend-whatsapp-reminders"',
    'APP_VERSION_OVERRIDE = "2026.09.15-persistant-supabase-v3.10.17-whatsapp-reminder-preview"',
    "version v3.10.17",
)

text = replace_once(
    text,
    '# Readiness sécurité : samedi + dimanche. Les envois automatiques du samedi restent désactivés.',
    '# Readiness sécurité : samedi + dimanche, alignée avec les rappels du mercredi et du vendredi.',
    "commentaire readiness week-end",
)

text = replace_once(
    text,
    'st.caption("Le contrôle de préparation couvre samedi + dimanche ; les rappels automatiques du samedi ne sont pas encore activés.")',
    'st.caption("Le contrôle de préparation et les rappels du mercredi/vendredi couvrent samedi + dimanche.")',
    "caption rappels week-end",
)

marker = '        st.divider()\\n        st.markdown("### \\U0001f6a6 Autorisation de l\\\'envoi automatique")\\n'
preview = (
    '        st.divider()\\n'
    '        st.markdown("### 🔎 Aperçu des prochains rappels WhatsApp")\\n'
    '        _wa_preview_rows = reminder_preview_rows(state, reference_day=_now.date())\\n'
    '        if _wa_preview_rows:\\n'
    '            _wa_preview_summary = reminder_preview_summary(_wa_preview_rows)\\n'
    '            _wa_weekend_label = _wa_preview_summary["weekend_label"]\\n'
    '            _wa_wednesday_label = _wa_preview_summary["wednesday_label"]\\n'
    '            _wa_friday_label = _wa_preview_summary["friday_label"]\\n'
    '            st.info(\\n'
    '                f"Prochain week-end liturgique : dimanche {_wa_weekend_label} · "\\n'
    '                f"rappel mercredi {_wa_wednesday_label} · "\\n'
    '                f"rappel vendredi {_wa_friday_label}."\\n'
    '            )\\n'
    '            _wa_p1, _wa_p2, _wa_p3, _wa_p4 = st.columns(4)\\n'
    '            _wa_p1.metric("Destinataires", _wa_preview_summary["recipients"])\\n'
    '            _wa_p2.metric("Prêts", _wa_preview_summary["ready"])\\n'
    '            _wa_p3.metric("Bloqués", _wa_preview_summary["blocked"])\\n'
    '            _wa_p4.metric(\\n'
    '                "Rappels déjà envoyés",\\n'
    '                _wa_preview_summary["wednesday_sent"] + _wa_preview_summary["friday_sent"],\\n'
    '            )\\n'
    '            st.dataframe(\\n'
    '                reminder_preview_display_rows(_wa_preview_rows),\\n'
    '                use_container_width=True,\\n'
    '                hide_index=True,\\n'
    '            )\\n'
    '            st.caption(\\n'
    '                "Cet aperçu n’envoie aucun message. Il reproduit uniquement le plan "\\n'
    '                "du moteur Cloud API pour le prochain week-end."\\n'
    '            )\\n'
    '        else:\\n'
    '            st.info("Aucun prochain week-end publié à prévisualiser.")\\n\\n'
)
text = replace_once(text, marker, preview + marker, "aperçu avant autorisation")

namespace_marker = '        "whatsapp_display_rows": whatsapp_display_rows,\n'
namespace_insert = (
    namespace_marker
    + '        "reminder_preview_rows": reminder_preview_rows,\n'
    + '        "reminder_preview_summary": reminder_preview_summary,\n'
    + '        "reminder_preview_display_rows": reminder_preview_display_rows,\n'
)
text = replace_once(text, namespace_marker, namespace_insert, "namespace aperçu rappels")

PATH.write_text(text, encoding="utf-8")
print("v3.10.17 reminder preview patched")
