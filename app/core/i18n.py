"""Customer-facing texts in Kazakh, Russian and English (SRS 7).

Each key has a template per language, filled with ``str.format``. A missing
language falls back to English. Users pick their language on their profile
(``preferred_language``); messages to people without an account use the
buyer's language.
"""

from typing import Literal

Language = Literal["en", "ru", "kk"]
LANGUAGES: tuple[str, ...] = ("en", "ru", "kk")
DEFAULT_LANGUAGE: Language = "en"

_CATALOG: dict[str, dict[str, str]] = {
    # --- Account -------------------------------------------------------------
    "verify_email.title": {
        "en": "Confirm your BiletFlow email address",
        "ru": "Подтвердите адрес электронной почты в BiletFlow",
        "kk": "BiletFlow-тағы электрондық поштаңызды растаңыз",
    },
    "verify_email.body": {
        "en": "Hello {name},\n\nConfirm your email address to finish setting up your "
        "BiletFlow account:\n{link}\n\nThe link expires in {hours} hours. If you did "
        "not create this account, ignore this email.",
        "ru": "Здравствуйте, {name}!\n\nПодтвердите адрес почты, чтобы завершить "
        "настройку аккаунта BiletFlow:\n{link}\n\nСсылка действует {hours} ч. Если вы "
        "не создавали аккаунт, просто проигнорируйте это письмо.",
        "kk": "Сәлеметсіз бе, {name}!\n\nBiletFlow аккаунтын баптауды аяқтау үшін "
        "поштаңызды растаңыз:\n{link}\n\nСілтеме {hours} сағат жарамды. Егер аккаунт "
        "ашпаған болсаңыз, бұл хатты елемеңіз.",
    },
    "password_reset.title": {
        "en": "Reset your BiletFlow password",
        "ru": "Сброс пароля BiletFlow",
        "kk": "BiletFlow құпиясөзін қалпына келтіру",
    },
    "password_reset.body": {
        "en": "Hello {name},\n\nUse this link to choose a new password:\n{link}\n\n"
        "The link expires in {minutes} minutes and works once. If you did not ask for "
        "a reset, ignore this email.",
        "ru": "Здравствуйте, {name}!\n\nЧтобы задать новый пароль, перейдите по "
        "ссылке:\n{link}\n\nСсылка действует {minutes} мин и только один раз. Если вы "
        "не запрашивали сброс, проигнорируйте это письмо.",
        "kk": "Сәлеметсіз бе, {name}!\n\nЖаңа құпиясөз орнату үшін мына сілтемені "
        "ашыңыз:\n{link}\n\nСілтеме {minutes} минут және бір рет қана жарамды. Егер "
        "сіз сұрамаған болсаңыз, бұл хатты елемеңіз.",
    },
    # --- Orders and tickets --------------------------------------------------------
    "order_confirmed.title": {
        "en": "Your tickets for {event}",
        "ru": "Ваши билеты на «{event}»",
        "kk": "«{event}» іс-шарасына билеттеріңіз",
    },
    "order_confirmed.body": {
        "en": "Hello {name},\n\nYour order for {event} is confirmed.\n\n{summary}\n\n"
        "Your tickets are attached as a PDF you can print or show on your phone. You "
        "can also open them any time: {link}",
        "ru": "Здравствуйте, {name}!\n\nВаш заказ на «{event}» подтверждён.\n\n"
        "{summary}\n\nБилеты приложены в PDF: их можно распечатать или показать с "
        "телефона. Они всегда доступны здесь: {link}",
        "kk": "Сәлеметсіз бе, {name}!\n\n«{event}» тапсырысыңыз расталды.\n\n{summary}"
        "\n\nБилеттер PDF түрінде тіркелген: басып шығаруға немесе телефоннан көрсетуге "
        "болады. Оларды кез келген уақытта осы жерден ашасыз: {link}",
    },
    "order_confirmed.in_app": {
        "en": "Your order for {event} is confirmed. Your tickets are ready.",
        "ru": "Заказ на «{event}» подтверждён. Билеты готовы.",
        "kk": "«{event}» тапсырысы расталды. Билеттеріңіз дайын.",
    },
    "guest_ticket.title": {
        "en": "Your ticket for {event}",
        "ru": "Ваш билет на «{event}»",
        "kk": "«{event}» іс-шарасына билетіңіз",
    },
    "guest_ticket.body": {
        "en": "Hello {name},\n\n{buyer} got you a ticket for {event}. It is attached as "
        "a PDF you can print or show on your phone.",
        "ru": "Здравствуйте, {name}!\n\n{buyer} оформил(а) для вас билет на «{event}». "
        "Он приложен в PDF: его можно распечатать или показать с телефона.",
        "kk": "Сәлеметсіз бе, {name}!\n\n{buyer} сізге «{event}» іс-шарасына билет "
        "алды. Ол PDF түрінде тіркелген: басып шығаруға немесе телефоннан көрсетуге "
        "болады.",
    },
    "ticket_summary.free": {"en": "Free", "ru": "Бесплатно", "kk": "Тегін"},
    "ticket_summary.paid": {
        "en": "{amount} KZT (simulated)",
        "ru": "{amount} ₸ (демонстрация)",
        "kk": "{amount} ₸ (демонстрация)",
    },
    "ticket_summary.discount": {
        "en": " after {discount} KZT off with code {code}",
        "ru": " с учётом скидки {discount} ₸ по коду {code}",
        "kk": " {code} коды бойынша {discount} ₸ жеңілдікпен",
    },
    "ticket_summary.body": {
        "en": "Tickets:\n{lines}\n\nTotal: {total}",
        "ru": "Билеты:\n{lines}\n\nИтого: {total}",
        "kk": "Билеттер:\n{lines}\n\nБарлығы: {total}",
    },
    "payment_failed.title": {
        "en": "Payment failed for {event}",
        "ru": "Оплата не прошла: «{event}»",
        "kk": "Төлем өтпеді: «{event}»",
    },
    "payment_failed.body": {
        "en": "Hello {name},\n\nYour payment for {event} did not go through ({reason}). "
        "No tickets were issued.\n\nYour places are held until {until}. Try again: "
        "{link}",
        "ru": "Здравствуйте, {name}!\n\nОплата заказа на «{event}» не прошла "
        "({reason}). Билеты не выпущены.\n\nМеста забронированы до {until}. "
        "Попробуйте ещё раз: {link}",
        "kk": "Сәлеметсіз бе, {name}!\n\n«{event}» төлемі өтпеді ({reason}). Билеттер "
        "шығарылмады.\n\nОрындар {until} дейін сақталады. Қайта көріңіз: {link}",
    },
    "refund_completed.title": {
        "en": "Refund for {event}",
        "ru": "Возврат средств: «{event}»",
        "kk": "Қаражатты қайтару: «{event}»",
    },
    "refund_completed.body": {
        "en": "Hello {name},\n\nYour order for {event} has been refunded in full: "
        "{amount} KZT (simulated; no real money moves in this demonstration).\n"
        "Reason: {reason}\n\nYour tickets for this order are no longer valid.",
        "ru": "Здравствуйте, {name}!\n\nЗаказ на «{event}» возвращён полностью: "
        "{amount} ₸ (демонстрация, реальные деньги не переводятся).\nПричина: "
        "{reason}\n\nБилеты этого заказа больше недействительны.",
        "kk": "Сәлеметсіз бе, {name}!\n\n«{event}» тапсырысы толық қайтарылды: "
        "{amount} ₸ (демонстрация, нақты ақша аударылмайды).\nСебебі: {reason}\n\n"
        "Бұл тапсырыстың билеттері енді жарамсыз.",
    },
    "registration_cancelled.title": {
        "en": "Your registration for {event} was cancelled",
        "ru": "Ваша регистрация на «{event}» отменена",
        "kk": "«{event}» тіркелуіңіз жойылды",
    },
    "registration_cancelled.body": {
        "en": "Hello {name},\n\nThe organizer cancelled your free registration for "
        "{event}.\nReason: {reason}\n\nYour tickets for it are no longer valid.",
        "ru": "Здравствуйте, {name}!\n\nОрганизатор отменил вашу бесплатную "
        "регистрацию на «{event}».\nПричина: {reason}\n\nБилеты больше "
        "недействительны.",
        "kk": "Сәлеметсіз бе, {name}!\n\nҰйымдастырушы «{event}» тегін тіркелуіңізді "
        "жойды.\nСебебі: {reason}\n\nБилеттер енді жарамсыз.",
    },
    # --- Events ------------------------------------------------------------------------
    "event_cancelled.title": {
        "en": "{event} is cancelled",
        "ru": "«{event}» отменено",
        "kk": "«{event}» болмайды",
    },
    "event_cancelled.body": {
        "en": "Hello {name},\n\nThe organizer has cancelled {event}, planned for "
        "{when}. Your tickets are no longer valid.",
        "ru": "Здравствуйте, {name}!\n\nОрганизатор отменил «{event}», "
        "запланированное на {when}. Ваши билеты больше недействительны.",
        "kk": "Сәлеметсіз бе, {name}!\n\nҰйымдастырушы {when} күнге жоспарланған "
        "«{event}» іс-шарасын болдырмады. Билеттеріңіз енді жарамсыз.",
    },
    "event_updated.title": {
        "en": "{event} has changed",
        "ru": "Изменения в «{event}»",
        "kk": "«{event}» өзгерді",
    },
    "event_updated.body": {
        "en": "Hello {name},\n\nThe organizer updated {event}:\n{changes}\n\nYour "
        "tickets stay valid. Details: {link}",
        "ru": "Здравствуйте, {name}!\n\nОрганизатор изменил «{event}»:\n{changes}\n\n"
        "Ваши билеты остаются действительными. Подробнее: {link}",
        "kk": "Сәлеметсіз бе, {name}!\n\nҰйымдастырушы «{event}» іс-шарасын "
        "өзгертті:\n{changes}\n\nБилеттеріңіз жарамды болып қалады. Толығырақ: {link}",
    },
    "change.start_at": {
        "en": "Starts: {value}",
        "ru": "Начало: {value}",
        "kk": "Басталуы: {value}",
    },
    "change.end_at": {
        "en": "Ends: {value}",
        "ru": "Окончание: {value}",
        "kk": "Аяқталуы: {value}",
    },
    "change.venue_name": {
        "en": "Venue: {value}",
        "ru": "Площадка: {value}",
        "kk": "Өтетін орны: {value}",
    },
    "change.venue_address": {
        "en": "Address: {value}",
        "ru": "Адрес: {value}",
        "kk": "Мекенжайы: {value}",
    },
    "change.city": {
        "en": "City: {value}",
        "ru": "Город: {value}",
        "kk": "Қала: {value}",
    },
    "change.timezone": {
        "en": "Time zone: {value}",
        "ru": "Часовой пояс: {value}",
        "kk": "Уақыт белдеуі: {value}",
    },
    "event_suspended.title": {
        "en": "{event} was suspended by BiletFlow",
        "ru": "«{event}» приостановлено командой BiletFlow",
        "kk": "«{event}» BiletFlow командасымен тоқтатылды",
    },
    "event_suspended.body": {
        "en": "Hello {name},\n\nThe BiletFlow team has suspended {event}. It is hidden from attendees and no new orders can be placed.\nReason: {reason}\n\nContact platform support to resolve this.",
        "ru": "Здравствуйте, {name}!\n\nКоманда BiletFlow приостановила «{event}». Событие скрыто от посетителей, новые заказы недоступны.\nПричина: {reason}\n\nОбратитесь в поддержку платформы.",
        "kk": "Сәлеметсіз бе, {name}!\n\nBiletFlow командасы «{event}» іс-шарасын тоқтатты. Ол келушілерден жасырылды, жаңа тапсырыс беру мүмкін емес.\nСебебі: {reason}\n\nПлатформа қолдауына хабарласыңыз.",
    },
    "event_restored.title": {
        "en": "{event} is visible again",
        "ru": "«{event}» снова доступно",
        "kk": "«{event}» қайта қолжетімді",
    },
    "event_restored.body": {
        "en": "Hello {name},\n\nThe BiletFlow team has lifted the suspension of {event}. Attendees can see it and order again.",
        "ru": "Здравствуйте, {name}!\n\nКоманда BiletFlow сняла приостановку с «{event}». Посетители снова видят событие и могут оформлять заказы.",
        "kk": "Сәлеметсіз бе, {name}!\n\nBiletFlow командасы «{event}» тоқтатылуын алып тастады. Келушілер оны қайта көріп, тапсырыс бере алады.",
    },
    # --- Organizers ------------------------------------------------------------------
    "paid_sales_activated.title": {
        "en": "Paid sales are open for {event}",
        "ru": "Платные продажи открыты: «{event}»",
        "kk": "Ақылы сату ашылды: «{event}»",
    },
    "paid_sales_activated.body": {
        "en": "Hello {name},\n\nPaid tickets for {event} can now be bought. In this "
        "demonstration no real money is collected.",
        "ru": "Здравствуйте, {name}!\n\nТеперь на «{event}» можно купить платные "
        "билеты. В демонстрации реальные деньги не списываются.",
        "kk": "Сәлеметсіз бе, {name}!\n\n«{event}» іс-шарасына енді ақылы билет алуға "
        "болады. Демонстрацияда нақты ақша алынбайды.",
    },
    "paid_sales_suspended.title": {
        "en": "Paid sales suspended for {event}",
        "ru": "Платные продажи приостановлены: «{event}»",
        "kk": "Ақылы сату тоқтатылды: «{event}»",
    },
    "paid_sales_suspended.body": {
        "en": "Hello {name},\n\nThe BiletFlow team has suspended paid ticket sales for "
        "{event}.\nReason: {reason}\n\nFree registrations and tickets already sold are "
        "not affected. Payouts for this event are on hold until the review ends "
        "(simulated). Reply through platform support to resolve this.",
        "ru": "Здравствуйте, {name}!\n\nКоманда BiletFlow приостановила продажу платных "
        "билетов на «{event}».\nПричина: {reason}\n\nБесплатные регистрации и уже "
        "проданные билеты не затронуты. Выплаты по этому событию заморожены до конца "
        "проверки (демонстрация). Напишите в поддержку платформы.",
        "kk": "Сәлеметсіз бе, {name}!\n\nBiletFlow командасы «{event}» ақылы билет "
        "сатуын тоқтатты.\nСебебі: {reason}\n\nТегін тіркелу мен сатылған билеттерге "
        "әсер етпейді. Бұл іс-шара бойынша төлемдер тексеру аяқталғанша тоқтатылды "
        "(демонстрация). Платформа қолдауына жазыңыз.",
    },
    # "Organizer payout status" (SRS 4.10): the hold set by a suspension ends
    "paid_sales_resumed.title": {
        "en": "Paid sales and payouts resumed for {event}",
        "ru": "Платные продажи и выплаты возобновлены: «{event}»",
        "kk": "Ақылы сату мен төлемдер қайта басталды: «{event}»",
    },
    "paid_sales_resumed.body": {
        "en": "Hello {name},\n\nThe BiletFlow team has finished its review of {event}. "
        "Paid tickets can be bought again, and payouts for this event are no longer "
        "on hold. In this demonstration no real money is paid out.",
        "ru": "Здравствуйте, {name}!\n\nКоманда BiletFlow завершила проверку «{event}». "
        "Платные билеты снова можно купить, выплаты по этому событию больше не "
        "заморожены. В демонстрации реальные выплаты не производятся.",
        "kk": "Сәлеметсіз бе, {name}!\n\nBiletFlow командасы «{event}» тексеруін "
        "аяқтады. Ақылы билеттерді қайта сатып алуға болады, бұл іс-шара бойынша "
        "төлемдер енді тоқтатылмайды. Демонстрацияда нақты төлем жасалмайды.",
    },
    "payout_saved.title": {
        "en": "Payout account verified",
        "ru": "Счёт для выплат подтверждён",
        "kk": "Төлем шоты расталды",
    },
    "payout_saved.body": {
        "en": "Hello {name},\n\nYour payout account at {bank} is saved and verified "
        "(simulated). Ticket revenue would be paid there; no real payouts are made in "
        "this demonstration.",
        "ru": "Здравствуйте, {name}!\n\nСчёт для выплат в {bank} сохранён и "
        "подтверждён (демонстрация). Выручка поступала бы туда; в демонстрации "
        "реальные выплаты не производятся.",
        "kk": "Сәлеметсіз бе, {name}!\n\n{bank} банкіндегі төлем шоты сақталып, "
        "расталды (демонстрация). Түсім осы шотқа түсер еді; демонстрацияда нақты "
        "төлем жасалмайды.",
    },
    # --- Support --------------------------------------------------------------------
    "support_new.title": {
        "en": "New support case: {subject}",
        "ru": "Новое обращение: {subject}",
        "kk": "Жаңа өтініш: {subject}",
    },
    "support_new.body": {
        "en": "{actor} opened a support case.\n\n{message}\n\nReply: {link}",
        "ru": "{actor} создал(а) обращение в поддержку.\n\n{message}\n\nОтветить: {link}",
        "kk": "{actor} қолдауға өтініш жіберді.\n\n{message}\n\nЖауап беру: {link}",
    },
    "support_reply.title": {
        "en": "New reply: {subject}",
        "ru": "Новый ответ: {subject}",
        "kk": "Жаңа жауап: {subject}",
    },
    "support_reply.body": {
        "en": "{actor} wrote:\n\n{message}\n\nReply: {link}",
        "ru": "{actor} пишет:\n\n{message}\n\nОтветить: {link}",
        "kk": "{actor} жазды:\n\n{message}\n\nЖауап беру: {link}",
    },
    "support_assigned.title": {
        "en": "Support case assigned to you: {subject}",
        "ru": "Вам назначено обращение: {subject}",
        "kk": "Сізге өтініш тағайындалды: {subject}",
    },
    "support_assigned.body": {
        "en": "{actor} assigned you a support case.\n\nOpen it: {link}",
        "ru": "{actor} назначил(а) вам обращение.\n\nОткрыть: {link}",
        "kk": "{actor} сізге өтініш тағайындады.\n\nАшу: {link}",
    },
    "support_status.title": {
        "en": "Your support case is now {status}: {subject}",
        "ru": "Статус обращения: {status} — {subject}",
        "kk": "Өтініш күйі: {status} — {subject}",
    },
    "support_status.body": {
        "en": "{actor} changed the status of your case to {status}.\n\nOpen it: {link}",
        "ru": "{actor} изменил(а) статус вашего обращения: {status}.\n\nОткрыть: {link}",
        "kk": "{actor} өтінішіңіздің күйін өзгертті: {status}.\n\nАшу: {link}",
    },
    "support_escalated.title": {
        "en": "Escalated support case: {subject}",
        "ru": "Обращение передано платформе: {subject}",
        "kk": "Өтініш платформаға жіберілді: {subject}",
    },
    "support_escalated.body": {
        "en": "{actor} escalated a support case: {reason}\n\nOpen it: {link}",
        "ru": "{actor} передал(а) обращение команде платформы: {reason}\n\nОткрыть: {link}",
        "kk": "{actor} өтінішті платформа командасына жіберді: {reason}\n\nАшу: {link}",
    },
    "status.open": {"en": "Open", "ru": "Открыто", "kk": "Ашық"},
    "status.in_progress": {"en": "In Progress", "ru": "В работе", "kk": "Қаралуда"},
    "status.waiting_for_customer": {
        "en": "Waiting for Customer",
        "ru": "Ожидает ответа клиента",
        "kk": "Клиент жауабын күтуде",
    },
    "status.resolved": {"en": "Resolved", "ru": "Решено", "kk": "Шешілді"},
}


def t(key: str, language: str | None, **params: object) -> str:
    """The text for ``key`` in ``language`` (English if missing), filled in."""
    entry = _CATALOG[key]
    template = entry.get(language or DEFAULT_LANGUAGE) or entry[DEFAULT_LANGUAGE]
    return template.format(**params)


def keys() -> list[str]:
    return list(_CATALOG)
