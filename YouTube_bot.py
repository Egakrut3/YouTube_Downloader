# -*- coding: utf-8 -*-

import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build as build_drive_interactor

CLIENT_SECRET_FILE = 'client_secret_896999314143-o05ena12v20p4men0ljtiif24n1dunjk.apps.googleusercontent.com.json'
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def authenticate_google_drive():
    creds = None

    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES).run_local_server(port=0)

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build_drive_interactor('drive', 'v3', credentials=creds)

def get_drive_quota():
    quota = authenticate_google_drive().about().get(fields='storageQuota').execute()['storageQuota']
    return int(quota['limit']) - int(quota['usage'])

def delete_oldest():
    gdrive = authenticate_google_drive()
    file_list = gdrive.files().list(orderBy='createdTime', pageSize=1, fields='files(id)').execute()
    gdrive.files().delete(fileId=file_list['files'][0]['id']).execute()

from enum import Enum, auto
from telegram import InlineKeyboardButton, Update, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, ContextTypes, filters as telegram_filters
import uuid
from yt_dlp import YoutubeDL
from googleapiclient.http import MediaFileUpload

with open('telegram_token.txt', 'r') as tg_token:
    TELEGRAM_TOKEN = tg_token.read()

class ConversationStates(Enum):
    WAITING_LINK = auto()
    WAITING_FORMAT = auto()
    BAD_SOURCE = auto()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Отправьте мне ссылку, чтобы получить ссылку на Google Drive.')
    return ConversationStates.WAITING_LINK

async def show_formats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Ищу доступные форматы...')
    url = update.message.text.strip()
    aviable_resolutions = {}
    audio_asr = 0
    audio_compact_filesize = None
    audio_compact_id = None
    audio_best_filesize = None
    audio_best_abr = None
    audio_best_id = None

    try:
        with YoutubeDL() as ydl:
            formats = ydl.extract_info(url, download=False)['formats']

            for frm in formats:
                is_video = ('height' in frm and str(frm['height']).lower() != 'none' and
                            'fps' in frm and str(frm['fps']).lower() != 'none' and
                            'filesize' in frm and str(frm['filesize']).lower() != 'none' and
                            'vbr' in frm and str(frm['vbr']).lower() != 'none' and
                            'format_id' in frm)
                is_audio = ('asr' in frm and str(frm['asr']).lower() != 'none' and
                            'filesize' in frm and str(frm['filesize']).lower() != 'none' and
                            'abr' in frm and str(frm['abr']).lower() != 'none' and
                            'format_id' in frm)

                if is_video and not is_audio:
                    cur_height = int(frm['height'])
                    cur_fps = int(frm['fps'])
                    cur_filesize = int(frm['filesize'])

                    if cur_filesize > 1024 * 1024 * 1024:
                        continue

                    cur_vbr = int(frm['vbr'])
                    cur_id = frm['format_id']

                    if cur_height in aviable_resolutions:
                        prev_fps = aviable_resolutions[cur_height][0]

                        if prev_fps < cur_fps:
                            aviable_resolutions[cur_height] = (cur_fps, [cur_filesize, cur_id, cur_filesize, cur_vbr, cur_id])
                        elif prev_fps == cur_fps:
                            if aviable_resolutions[cur_height][1][0] > cur_filesize:
                                aviable_resolutions[cur_height][1][0] = cur_filesize
                                aviable_resolutions[cur_height][1][1] = cur_id

                            if aviable_resolutions[cur_height][1][3] < cur_vbr:
                                aviable_resolutions[cur_height][1][2] = cur_filesize
                                aviable_resolutions[cur_height][1][3] = cur_vbr
                                aviable_resolutions[cur_height][1][4] = cur_id
                    else:
                        aviable_resolutions[cur_height] = (cur_fps, [cur_filesize, cur_id, cur_filesize, cur_vbr, cur_id])

                if is_audio and not is_video:
                    cur_asr = int(frm['asr'])
                    cur_filesize = int(frm['filesize'])
                    cur_abr = int(frm['abr'])
                    cur_id = frm['format_id']

                    if cur_filesize > 50 * 1024 * 1024:
                        continue

                    if audio_asr < cur_asr:
                        audio_asr = cur_asr
                        audio_compact_filesize = cur_filesize
                        audio_compact_id = cur_id
                        audio_best_filesize = cur_filesize
                        audio_best_abr = cur_filesize
                        audio_best_id = cur_id
                    elif audio_asr == cur_asr:
                        if audio_compact_filesize > cur_filesize:
                            audio_compact_filesize = cur_filesize
                            audio_compact_id = cur_id

                        if audio_best_abr < cur_abr:
                            audio_best_filesize = cur_filesize
                            audio_best_abr = cur_abr
                            audio_best_id = cur_id
    except Exception as e:
        await update.reply_message('Введённая вами ссылка недействительна или не поддерживается этим ботом. Начните сначала с /start.')
        return ConversationHandler.END

    context.user_data['url'] = url
    
    if len(aviable_resolutions) == 0 or audio_asr == 0:
        await update.message.reply_text('Не удалось подробную информацию о видео, поэтому оно будет скачано без настройки качества. Желаете ли вы продолжить?',
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Да', callback_data='True'),
                                                                            InlineKeyboardButton('Нет', callback_data='False')]]))
        return ConversationStates.BAD_SOURCE

    keyboard = []

    for frm in sorted(aviable_resolutions):
        compact_filesize = aviable_resolutions[frm][1][0] + audio_compact_filesize
        compact_unit = 'B'

        if compact_filesize > 1024:
            compact_filesize /= 1024
            compact_unit = 'KB'

            if compact_filesize > 1024:
                compact_filesize /= 1024
                compact_unit = 'MB'

                if compact_filesize > 1024:
                    compact_filesize /= 1024
                    compact_unit = 'GB'

        compact_filesize = round(compact_filesize, 2)
        best_filesize = aviable_resolutions[frm][1][2] + audio_best_filesize
        best_unit = 'B'

        if best_filesize > 1024:
            best_filesize /= 1024
            best_unit = 'KB'

            if best_filesize > 1024:
                best_filesize /= 1024
                best_unit = 'MB'

                if best_filesize > 1024:
                    best_filesize /= 1024
                    best_unit = 'GB'

        best_filesize = round(best_filesize, 2)
        keyboard.append([InlineKeyboardButton(f'{frm}p ~{compact_filesize}{compact_unit}', callback_data=f'{aviable_resolutions[frm][1][1]}+{audio_compact_id}'),
                         InlineKeyboardButton(f'{frm}p ~{best_filesize}{best_unit}', callback_data=f'{aviable_resolutions[frm][1][4]}+{audio_best_id}')])

    await update.message.reply_text('Выберите разрешение: слева компактные варианты, справа варианты в самом лучшем качестве.',
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationStates.WAITING_FORMAT

async def upload_by_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    frm = query.data
    await query.edit_message_text('Скачиваю видео, подождите немного...')

    with YoutubeDL({'format': frm,
                    'outtmpl': f'file_{uuid.uuid4()}.%(ext)s'}) as ydl:
        output_path = ydl.prepare_filename(ydl.extract_info(context.user_data['url']))
        await query.edit_message_text('Загружаю на Google Drive...')

        while get_drive_quota() < os.path.getsize(output_path):
            delete_oldest()
        
        service = authenticate_google_drive()
        drive_file = service.files().create(body={'name': os.path.basename(output_path)},
                                            media_body=MediaFileUpload(output_path, resumable=True),
                                            fields='id, webViewLink').execute()
        service.permissions().create(fileId=drive_file['id'], body={'type': 'anyone', 'role': 'reader'}).execute()
        os.remove(output_path)
        await query.edit_message_text(f'Вот ваша ссылка на Google Drive: {drive_file['webViewLink']}')

    return ConversationHandler.END

async def best_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_answer = query.data
    if user_answer == 'True':
        try:
            with YoutubeDL({'format': 'best[filesize<=1.1G]',
                        'outtmpl': f'file_{uuid.uuid4()}.%(ext)s'}) as ydl:
                output_path = ydl.prepare_filename(ydl.extract_info(context.user_data['url']))
                await query.edit_message_text('Загружаю на Google Drive...')

                while get_drive_quota() < os.path.getsize(output_path):
                    delete_oldest()
                
                service = authenticate_google_drive()
                drive_file = service.files().create(body={'name': os.path.basename(output_path)},
                                                    media_body=MediaFileUpload(output_path, resumable=True),
                                                    fields='id, webViewLink').execute()
                service.permissions().create(fileId=drive_file['id'], body={'type': 'anyone', 'role': 'reader'}).execute()
                os.remove(output_path)
                await query.edit_message_text(f'Вот ваша ссылка на Google Drive: {drive_file['webViewLink']}')
        except Exception as e:
            await query.edit_message_text('Введённый вами источник совсем плох или не поддерживается этим ботом. Начните сначала с /start.')

    return ConversationHandler.END

async def something_strange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Я не понимаю, что вы имеете ввиду. Пожалуйста, следуйте указаниям бота.')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Сессия завершена.')
    return ConversationHandler.END

async def timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Ваша последняя сессия была завершена из-за долгого бездействия. Начните заново с /start.')
    return ConversationHandler.END

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(ConversationHandler(entry_points=[CommandHandler('start', start)],
                                    states={ConversationStates.WAITING_LINK: [MessageHandler(telegram_filters.TEXT & ~telegram_filters.COMMAND, show_formats)],
                                            ConversationStates.WAITING_FORMAT: [CallbackQueryHandler(upload_by_link)],
                                            ConversationStates.BAD_SOURCE: [CallbackQueryHandler(best_upload)],
                                            ConversationHandler.TIMEOUT: [MessageHandler(telegram_filters.ALL, timeout)]},
                                    fallbacks=[CommandHandler('cancel', cancel),
                                               MessageHandler(~telegram_filters.COMMAND, something_strange)],
                                    conversation_timeout=300))
print('Бот запущен!')
app.run_polling()