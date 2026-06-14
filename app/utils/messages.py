"""All user-facing messages in English, Hinglish, and Hindi."""

from typing import Any

# ---------------------------------------------------------------------------
# Patient messages
# ---------------------------------------------------------------------------

_PATIENT_MESSAGES: dict[str, dict[str, str]] = {
    "LANGUAGE_PICKER": {
        "english": "Hello! Welcome to *Sympto*. Please select your preferred language:",
        "hinglish": "Namaste! *Sympto* mein swagat hai. Pehle apni bhasha chunein:",
        "hindi": "नमस्ते! *सिम्प्टो* में आपका स्वागत है। पहले अपनी भाषा चुनें:",
    },
    "WELCOME_NEW": {
        "english": "I'll help you find the right doctor. I just need a little information first — please fill in the form below.",
        "hinglish": "Main aapko sahi doctor dhundhne mein help karunga. Pehle thodi si information chahiye — please neeche form fill karein.",
        "hindi": "मैं आपको सही डॉक्टर ढूंढने में मदद करूंगा। पहले थोड़ी जानकारी चाहिए — कृपया नीचे फ़ॉर्म भरें।",
    },
    "MENU_PROMPT": {
        "english": "Hello *{name}*. What would you like to do today?",
        "hinglish": "Namaste *{name}*. Aaj kya karna chahenge?",
        "hindi": "नमस्ते *{name}*। आज क्या करना चाहेंगे?",
    },
    "SYMPTOMS_PROMPT": {
        "english": "Okay *{name}*. What problem are you experiencing? Please describe your symptoms in detail.",
        "hinglish": "Theek hai *{name}*. Aapko kya problem ho rahi hai? Apne symptoms detail mein describe kijiye.",
        "hindi": "ठीक है *{name}*। आपको क्या समस्या हो रही है? अपने लक्षण विस्तार से बताइए।",
    },
    "EMERGENCY_WARNING": {
        "english": "⚠️ *These symptoms sound serious.* If you think this is an emergency, please call *112* now or go to the nearest Emergency Room. Your safety comes first. If you are feeling okay right now, I will find a doctor for you.",
        "hinglish": "⚠️ *Ye symptoms serious lag rahe hain.* Agar aapko lagta hai ye emergency hai, toh abhi *112* call karein ya nearest Emergency Room jayein. Apni safety sabse pehle. Agar abhi theek ho toh main aapke liye doctor dhundh deta hoon.",
        "hindi": "⚠️ *ये लक्षण गंभीर लग रहे हैं।* अगर आपको लगता है यह आपातकाल है, तो अभी *112* पर कॉल करें या नज़दीकी आपातकालीन कक्ष जाएं। आपकी सुरक्षा सबसे पहले। अगर अभी ठीक हैं तो मैं आपके लिए डॉक्टर ढूंढता हूं।",
    },
    "SPECIALIST_RECOMMENDATION": {
        "english": "Based on your symptoms, I think you should visit a *{specialties}*.",
        "hinglish": "Aapke symptoms ke hisaab se, mujhe lagta hai aapko *{specialties}* se milna chahiye.",
        "hindi": "आपके लक्षणों के आधार पर, मुझे लगता है आपको *{specialties}* से मिलना चाहिए।",
    },
    "SPECIALIST_RECOMMENDATION_UNCERTAIN": {
        "english": "I was unable to identify the exact specialist based on your symptoms. My best suggestion is to visit a *{specialties}* — but please share all your symptoms in detail with the doctor.",
        "hinglish": "Mujhe aapke symptoms ke basis pe sahi specialist identify karna mushkil tha. Mere best guess ke hisaab se aapko *{specialties}* se milna chahiye — lekin main suggest karunga ki doctor ko apne saare symptoms poori detail mein batayein.",
        "hindi": "आपके लक्षणों के आधार पर सही विशेषज्ञ पहचानना मुश्किल था। मेरे अनुसार आपको *{specialties}* से मिलना चाहिए — लेकिन डॉक्टर को पूरी जानकारी दें।",
    },
    "NO_DOCTORS_FOUND": {
        "english": "No *{specialization}* is currently available in our system for your symptoms. Please try again later.",
        "hinglish": "Aapke symptoms ke liye koi *{specialization}* abhi humare system me available nahi hai. Baad mein dobara try karein.",
        "hindi": "आपके लक्षणों के लिए कोई *{specialization}* अभी हमारे सिस्टम में उपलब्ध नहीं है। बाद में दोबारा कोशिश करें।",
    },
    "NO_DOCTORS_LOCAL": {
        "english": "No *{specialization}* was found near your location, but these doctors are available:",
        "hinglish": "Aapki location k paas abhi koi *{specialization}* nahi mila, lekin ye doctors available hain:",
        "hindi": "आपकी location के पास अभी कोई *{specialization}* नहीं मिला, लेकिन ये डॉक्टर उपलब्ध हैं:",
    },
    "DOCTORS_LIST_BODY": {
        "english": "These doctors are available 🩺\nSelect one to book an appointment:",
        "hinglish": "Ye doctors available hain 🩺\nKisi ek ko select karein aur appointment book karein:",
        "hindi": "ये डॉक्टर उपलब्ध हैं 🩺\nकिसी एक को चुनें और अपॉइंटमेंट बुक करें:",
    },
    "PICK_A_DAY": {
        "english": "*Dr. {name}* is available on these days this week:",
        "hinglish": "*Dr. {name}* is week mein in dinon available hain:",
        "hindi": "*डॉ. {name}* इस हफ़्ते इन दिनों उपलब्ध हैं:",
    },
    "NO_SLOTS_THIS_WEEK": {
        "english": "*Dr. {name}* has no availability in the next 7 days. Please choose a different doctor.",
        "hinglish": "*Dr. {name}* agle 7 din mein available nahi hain. Please koi aur doctor choose karein.",
        "hindi": "*डॉ. {name}* अगले 7 दिनों में उपलब्ध नहीं हैं। कृपया कोई अन्य डॉक्टर चुनें।",
    },
    "PICK_A_TIME": {
        "english": "Pick a time for *{date}*:",
        "hinglish": "*{date}* ke liye time chunein:",
        "hindi": "*{date}* के लिए समय चुनें:",
    },
    "APPOINTMENT_PENDING": {
        "english": "*Dr. {name}* has been sent your request. You will receive a message once they confirm.",
        "hinglish": "*Dr. {name}* ko request bhej di gayi hai. Jab wo confirm karenge, aapko message aayega.",
        "hindi": "*डॉ. {name}* को अनुरोध भेज दिया गया है। जब वे पुष्टि करेंगे, आपको संदेश आएगा।",
    },
    "APPOINTMENT_WAITING": {
        "english": "Your appointment request is with the doctor. Please wait for their response.",
        "hinglish": "Aapki appointment request doctor ke paas hai. Unka response aane ka wait karein.",
        "hindi": "आपकी अपॉइंटमेंट का अनुरोध डॉक्टर के पास है। उनके जवाब का इंतज़ार करें।",
    },
    "CANCEL_CONFIRM_PROMPT": {
        "english": "Are you sure you want to cancel your appointment request?",
        "hinglish": "Kya aap sach mein apni appointment cancel karna chahte hain?",
        "hindi": "क्या आप सच में अपनी अपॉइंटमेंट रद्द करना चाहते हैं?",
    },
    "APPOINTMENT_CANCELLED_PATIENT": {
        "english": "Your appointment request has been cancelled.",
        "hinglish": "Aapki appointment cancel ho gayi hai.",
        "hindi": "आपकी अपॉइंटमेंट रद्द कर दी गई है।",
    },
    "BOOKING_CONFIRMED": {
        "english": "Your appointment is confirmed.\n\nDr. *{name}*\n*{slot_day}, {slot_window}*\n*{clinic_name}*\n\nPlease arrive on time.",
        "hinglish": "Aapki appointment confirm ho gayi.\n\nDr. *{name}*\n*{slot_day}, {slot_window}*\n*{clinic_name}*\n\nPlease time pe pahunchein.",
        "hindi": "आपकी अपॉइंटमेंट कन्फ़र्म हो गई।\n\nडॉ. *{name}*\n*{slot_day}, {slot_window}*\n*{clinic_name}*\n\nकृपया समय पर पहुंचें।",
    },
    "DOCTOR_REJECTED": {
        "english": "*Dr. {name}* has not accepted this slot. Would you like to see other slots with the same doctor, or try a different doctor?",
        "hinglish": "*Dr. {name}* ne abhi ye slot accept nahi ki. Kya aap same doctor ke doosre slot dekhna chahenge, ya kisi aur doctor ko try karein?",
        "hindi": "*डॉ. {name}* ने अभी यह स्लॉट स्वीकार नहीं किया। क्या आप उसी डॉक्टर के दूसरे स्लॉट देखना चाहेंगे, या किसी अन्य डॉक्टर को आज़माएं?",
    },
    "DUPLICATE_BOOKING": {
        "english": "⚠️ You already have an appointment with *Dr. {name}* on *{slot_day}*. Please choose a different doctor or a different day.",
        "hinglish": "⚠️ Aapki *Dr. {name}* ke saath *{slot_day}* ko pehle se ek appointment hai. Please doosra doctor ya alag din choose karein.",
        "hindi": "⚠️ *डॉ. {name}* के साथ *{slot_day}* को पहले से एक अपॉइंटमेंट है। कृपया दूसरा डॉक्टर या अलग दिन चुनें।",
    },
    "NO_APPOINTMENTS": {
        "english": "You have no appointments yet. Tap 'Symptoms Analysis' to get started.",
        "hinglish": "Aapki abhi tak koi appointment nahi hai. 'Syptoms Analysis' karein.",
        "hindi": "आपकी अभी तक कोई अपॉइंटमेंट नहीं है। 'लक्षणों का विश्लेषण' करें।",
    },
    "BROWSE_SPECIALTY_PROMPT": {
        "english": "Which type of specialist would you like to see?",
        "hinglish": "Aap kaun se specialist se milna chahte hain?",
        "hindi": "आप किस विशेषज्ञ से मिलना चाहते हैं?",
    },
    "NO_SPECIALTIES_AVAILABLE": {
        "english": "No specialists available right now. Please try 'Symptoms Analysis' instead.",
        "hinglish": "Abhi koi specialist available nahi. Please 'Symptoms Analysis' try karein.",
        "hindi": "अभी कोई विशेषज्ञ उपलब्ध नहीं। कृपया लक्षणों का विश्लेषण आज़माएं।",
    },
    "LLM_BUSY": {
        "english": "The AI service is currently busy. Please try again in a moment.",
        "hinglish": "Abhi AI service thodi busy hai. Thodi der baad dobara try karein.",
        "hindi": "अभी AI सेवा थोड़ी व्यस्त है। थोड़ी देर बाद दोबारा कोशिश करें।",
    },
    "GENERIC_ERROR": {
        "english": "Something went wrong. Please try again.",
        "hinglish": "Kuch problem aayi. Please dobara try karein.",
        "hindi": "कुछ समस्या आई। कृपया दोबारा कोशिश करें।",
    },
    "COMPLETE_PROFILE_FIRST": {
        "english": "Please complete the profile form first. After that you can do a Symptoms Analysis.",
        "hinglish": "Please pehle profile form complete karein. Iske baad aap appointments book kar sakte hain.",
        "hindi": "कृपया पहले प्रोफ़ाइल फ़ॉर्म पूरा करें। इसके बाद आप अपॉइंटमेंट बुक कर सकते हैं।",
    },
    "LANGUAGE_CHANGED": {
        "english": "Language updated.",
        "hinglish": "Bhasha update ho gayi.",
        "hindi": "भाषा अपडेट हो गई।",
    },
    "BTN_BOOK": {
        "english": "Symptoms Analysis",
        "hinglish": "Syptoms Analysis",
        "hindi": "लक्षणों का विश्लेषण",
    },
    "BTN_BROWSE_DOCTORS": {
        "english": "Browse Doctors",
        "hinglish": "Doctor Browse Karein",
        "hindi": "डॉक्टर ब्राउज़ करें",
    },
    "BTN_VIEW": {
        "english": "My Appointments",
        "hinglish": "Mere Appointments",
        "hindi": "मेरी अपॉइंटमेंट",
    },
    "BTN_UPDATE_PROFILE": {
        "english": "Update Profile",
        "hinglish": "Profile Update",
        "hindi": "प्रोफ़ाइल अपडेट",
    },
    "BTN_CHANGE_LANGUAGE": {
        "english": "Change Language / भाषा बदलें",
        "hinglish": "Change Language / भाषा बदलें",
        "hindi": "Change Language",
    },
    "REMINDER_PATIENT": {
        "english": "⏰ Reminder: Your appointment with Dr. {doctor_name} is at {time}. Please arrive on time.",
        "hinglish": "⏰ Reminder: Aapka appointment Dr. {doctor_name} ke saath {time} pe hai. Please time pe pahunchein.",
        "hindi": "⏰ याद दिलाना: आपकी अपॉइंटमेंट डॉ. {doctor_name} के साथ {time} पर है। कृपया समय पर पहुंचें।",
    },
}

# ---------------------------------------------------------------------------
# Doctor messages (always English)
# ---------------------------------------------------------------------------

DOCTOR_MESSAGES: dict[str, str] = {
    "ALREADY_REGISTERED": "You are already registered with us. ✅ To update your slots, please use *Update availability*.",
    "REGISTRATION_PROMPT": "Welcome. To register with Sympto network, please fill in the form below.",
    "ONBOARDING_DONE": "✅ *Application Submitted!* We've received your registration. Our team will review your details and notify you once your profile is live. When someone books an appointment, you will receive a notification here.",
    "UPDATE_AVAILABILITY_PROMPT": "To update your availability, please fill in the form below.",
    "DOCTOR_APPROVED": "✅ *Great news!* Your Sympto profile has been approved. Patients in your area can now find and book appointments with you.",
    "DOCTOR_REJECTED_ADMIN": "We're sorry — your Sympto application could not be approved at this time. Please contact our support team for more information.",
    "DOCTOR_MEMBER_GRANTED": "🌟 *Welcome to Sympto Premium!* You are now a verified member. Your profile will be featured at the top of patient searches in your area.",
    "DOCTOR_MEMBER_REVOKED": "Your Sympto Premium membership has ended. Your profile remains active but will no longer be featured at the top of search results.",
    "CONFIRMATION_TO_DOCTOR": "Appointment confirmed. We have notified the patient as well.",
    "REJECTION_TO_DOCTOR": "We have rejected the appointment request. Patient has been informed that you are not available at the requested time, and to choose a different slot or doctor.",
    "APPOINTMENT_CANCELLED": "The patient *{name}* has cancelled their appointment request.",
    "CLINIC_ADDED": "✅ Clinic added successfully!",
    "AVAILABILITY_UPDATED": "Your availability has been updated. ✅ Patients will see your new slots in the finder.",
    "VACATION_SAVED": "Leave saved! 🏖️ You won't appear to patients from *{start}* to *{end}*.",
    "VACATION_CANCELLED": "Leave cancelled. You're now visible to patients again. ✅",
    "VACATION_INVALID_DATES": "End date cannot be before start date. Please try again.",
    "REMINDER_DOCTOR": "⏰ Reminder: You have an appointment with {patient_name} at {time}.",
}


def get_message(key: str, language: str, **kwargs: Any) -> str:
    """Return a localized patient message, falling back to English."""
    lang = language if language in {"english", "hindi", "hinglish"} else "english"
    messages = _PATIENT_MESSAGES.get(key, {})
    text = messages.get(lang) or messages.get("english", key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text
