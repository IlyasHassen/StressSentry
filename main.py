import requests
import cohere
from datetime import date, timedelta
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "7891796892:AAFKpJ2jiV0o2TSRdr1s2dK9mrL1p7Nxx4c"
OURA_TOKEN = "YBXDKEJVOH33MQZK4SSNATV4SCBLDFUI"
COHERE_API_KEY = "XlPrqoZgg6Jxfhjr6Y6twR3lBtZgoiGmRVl14rt6"

co = cohere.Client(COHERE_API_KEY)
ASKING_RESSENTI, ASKING_PSS = range(2)

PSS_QUESTIONS = [
    "1. Au cours du dernier mois, à quelle fréquence avez-vous été bouleversé parce que quelque chose d’inattendu vous est arrivé ? (0=Jamais, 4=Très souvent)",
    "2. Vous êtes-vous senti incapable de contrôler les choses importantes dans votre vie ?",
    "3. Avez-vous souvent ressenti de la nervosité ou du stress ?",
    "4. Avez-vous eu confiance en votre capacité à gérer vos problèmes personnels ? (0=Très souvent, 4=Jamais)",
    "5. Avez-vous eu l’impression que les choses allaient comme vous le vouliez ? (0=Très souvent, 4=Jamais)",
    "6. Avez-vous eu du mal à gérer toutes les choses à faire ?",
    "7. Avez-vous pu contrôler les irritations dans votre vie ? (0=Très souvent, 4=Jamais)",
    "8. Avez-vous eu le sentiment que les difficultés s’accumulaient au point de ne pas pouvoir les surmonter ?",
    "9. Avez-vous été en colère à cause de choses hors de votre contrôle ?",
    "10. Avez-vous eu le sentiment que tout allait bien ? (0=Très souvent, 4=Jamais)"
]

# --- OURA DATA ---
def get_oura_data_last_days(days=7):
    HEADERS = {"Authorization": f"Bearer {OURA_TOKEN}"}
    end_date = date.today()
    start_date = end_date - timedelta(days=days-1)
    params = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    }
    def fetch(endpoint):
        url = f"https://api.ouraring.com/v2/usercollection/{endpoint}"
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            print(f"Erreur Oura ({endpoint}): {e}")
            return []
    sleep = fetch("daily_sleep")
    readiness = fetch("daily_readiness")
    activity = fetch("daily_activity")
    data = []
    for i in range(days):
        d = (start_date + timedelta(days=i)).isoformat()
        s = next((x for x in sleep if x.get("day") == d), {})
        r = next((x for x in readiness if x.get("day") == d), {})
        a = next((x for x in activity if x.get("day") == d), {})
        data.append({
            "date": d,
            "sommeil_h": round(s.get("duration", 0) / 3600, 2) if s else 0,
            "readiness": r.get("score", "N/A") if r else "N/A",
            "pas": a.get("steps", 0) if a else 0,
            "fc_moy": s.get("average_hr", "N/A") if s else "N/A"
        })
    if all(
        d["sommeil_h"] == 0 and d["readiness"] in (0, "N/A") and d["pas"] == 0
        for d in data
    ):
        return None
    return data

# --- COHERE GENERATION ---
def recommander_cohere(ressenti, donnees_oura, pss_score=None):
    resume = "\n".join([
        f"{d['date']} : sommeil {d['sommeil_h']}h, readiness {d['readiness']}, pas {d['pas']}, FC {d['fc_moy']} bpm"
        for d in donnees_oura
    ]) if donnees_oura else "Aucune donnée Oura disponible."
    prompt = (
        f"Données Oura sur 7 jours :\n{resume}\n"
        f"Ressenti : {ressenti}\n"
        "Réponse en anglais.\n"
        "Donne une recommandation personnalisée pour la gestion du stress et du bien-être, en trois parties :\n"
        "1. Données situation : synthèse des données et du ressenti\n"
        "2. Action immédiate (biofeedback, respiration, relaxation, marche et autres)\n"
        "3. Conseil pour les prochains jours\n"
        "Je veux une réponse complète et détaillée avec maximum 300 caractères, je veux que ça se finisse par une phrase complète.\n"
    )
    try:
        response = co.generate(
            model="command",
            prompt=prompt,
            max_tokens=300,
            temperature=0.7,
        )
        return response.generations[0].text.strip()
    except Exception as e:
        print(f"Erreur Cohere : {e}")
        return "Le service de génération Cohere est temporairement indisponible. Merci de réessayer plus tard."

# --- Commandes Telegram ---

async def historique(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    donnees = get_oura_data_last_days(7)
    if not donnees:
        await update.message.reply_text("Aucune donnée Oura Ring récente trouvée.")
        return
    msg = "Historique Oura des 7 derniers jours :\n"
    for d in donnees:
        msg += (
            f"- {d['date']} : sommeil {d['sommeil_h']}h | readiness {d['readiness']} | pas {d['pas']} | fréquence cardiaque moyenne {d['fc_moy']} bpm\n"
        )
    await update.message.reply_text(msg)

async def pss_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['pss_responses'] = []
    ctx.user_data['pss_q'] = 0
    await update.message.reply_text(PSS_QUESTIONS[0])
    return ASKING_PSS

async def pss_handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        resp = int(update.message.text)
        if resp < 0 or resp > 4:
            raise ValueError()
    except:
        await update.message.reply_text("Répondez par 0, 1, 2, 3 ou 4.")
        return ASKING_PSS
    ctx.user_data['pss_responses'].append(resp)
    ctx.user_data['pss_q'] += 1
    if ctx.user_data['pss_q'] < len(PSS_QUESTIONS):
        await update.message.reply_text(PSS_QUESTIONS[ctx.user_data['pss_q']])
        return ASKING_PSS
    else:
        pss_score = sum(ctx.user_data['pss_responses'])
        await update.message.reply_text(f"Votre score PSS-10 est {pss_score}/40.")
        return ConversationHandler.END

async def questions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Question ouverte :\n"
        "Qu'est-ce qui vous aide à vous détendre après une journée difficile ?\n\n"
        "Question fermée :\n"
        "Avez-vous pratiqué une technique de respiration aujourd'hui ? (oui/non)"
    )
    await update.message.reply_text(msg) 
    

async def ressenti_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Décris ton ressenti (fatigue, stress, humeur, contexte)."
    )
    return ASKING_RESSENTI

async def ressenti_handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ressenti = update.message.text
    donnees = get_oura_data_last_days(7)
    recommandation = recommander_cohere(ressenti, donnees)
    msg = "Recommandation personnalisée :\n" + recommandation
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Conversation annulée.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- HELP COMMAND ---
async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Voici les commandes disponibles :\n\n"
        "/historique - Affiche les données Oura des 7 derniers jours (sommeil, readiness, activité).\n\n"
        "/pss - Lance le questionnaire PSS-10 pour évaluer ton niveau de stress perçu.\n\n"
        "/questions - Pose une question ouverte et une question fermée pour mieux comprendre ton état.\n\n"
        "/ressenti - Permet de décrire ton ressenti (fatigue, stress, humeur) et reçoit une recommandation personnalisée.\n\n"
        "/cancel - Annule la conversation en cours.\n\n"
        "/help - Affiche ce message d’aide.\n\n"
        "Utilise ces commandes pour interagir avec le bot et obtenir un suivi personnalisé."
    )
    await update.message.reply_text(help_text)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    pss_conv = ConversationHandler(
        entry_points=[CommandHandler("pss", pss_start)],
        states={ASKING_PSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, pss_handle)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    ressenti_conv = ConversationHandler(
        entry_points=[CommandHandler("ressenti", ressenti_start)],
        states={ASKING_RESSENTI: [MessageHandler(filters.TEXT & ~filters.COMMAND, ressenti_handle)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("historique", historique))
    app.add_handler(CommandHandler("questions", questions))
    app.add_handler(pss_conv)
    app.add_handler(ressenti_conv)
    app.add_handler(CommandHandler("help", help_command))
    print("StressSentry")
    app.run_polling()