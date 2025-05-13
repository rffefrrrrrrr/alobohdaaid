from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def create_keyboard(buttons, row_width=1):
    """
    إنشاء لوحة مفاتيح مخصصة باستخدام الأزرار المقدمة
    
    Args:
        buttons: قائمة من الأزرار، كل زر هو قاموس يحتوي على 'text' و 'callback_data'
        row_width: عدد الأزرار في كل صف
        
    Returns:
        InlineKeyboardMarkup: لوحة المفاتيح المنشأة
    """
    keyboard = []
    row = []
    
    for i, button in enumerate(buttons):
        # إذا كان الزر قاموس، قم بإنشاء زر من البيانات
        if isinstance(button, dict):
            text = button.get('text', 'زر')
            callback_data = button.get('callback_data', f'button_{i}')
            url = button.get('url', None)
            
            if url:
                row.append(InlineKeyboardButton(text, url=url))
            else:
                row.append(InlineKeyboardButton(text, callback_data=callback_data))
        # إذا كان الزر كائن InlineKeyboardButton بالفعل، استخدمه مباشرة
        elif isinstance(button, InlineKeyboardButton):
            row.append(button)
        
        # إذا وصلنا إلى عرض الصف المطلوب أو نهاية القائمة، أضف الصف إلى لوحة المفاتيح
        if len(row) == row_width or i == len(buttons) - 1:
            keyboard.append(row)
            row = []
    
    # إذا كان هناك أزرار متبقية في الصف، أضفها
    if row:
        keyboard.append(row)
    
    return InlineKeyboardMarkup(keyboard)

def create_menu_keyboard(items, prefix='menu', row_width=1, add_back=True, add_cancel=True):
    """
    إنشاء لوحة مفاتيح قائمة مع خيارات العودة والإلغاء
    
    Args:
        items: قائمة من العناصر، كل عنصر هو قاموس يحتوي على 'text' و 'value'
        prefix: بادئة لبيانات الاستدعاء
        row_width: عدد الأزرار في كل صف
        add_back: إضافة زر العودة
        add_cancel: إضافة زر الإلغاء
        
    Returns:
        InlineKeyboardMarkup: لوحة المفاتيح المنشأة
    """
    buttons = []
    
    # إضافة عناصر القائمة
    for item in items:
        if isinstance(item, dict):
            text = item.get('text', 'عنصر')
            value = item.get('value', '')
            buttons.append({
                'text': text,
                'callback_data': f"{prefix}:{value}"
            })
        elif isinstance(item, tuple) and len(item) == 2:
            text, value = item
            buttons.append({
                'text': text,
                'callback_data': f"{prefix}:{value}"
            })
    
    # إضافة أزرار التنقل
    navigation_buttons = []
    
    if add_back:
        navigation_buttons.append({
            'text': '🔙 رجوع',
            'callback_data': 'back'
        })
    
    if add_cancel:
        navigation_buttons.append({
            'text': '❌ إلغاء',
            'callback_data': 'cancel'
        })
    
    # إنشاء لوحة المفاتيح
    keyboard = []
    row = []
    
    # إضافة أزرار القائمة
    for i, button in enumerate(buttons):
        row.append(InlineKeyboardButton(button['text'], callback_data=button['callback_data']))
        
        if len(row) == row_width or i == len(buttons) - 1:
            keyboard.append(row)
            row = []
    
    # إضافة أزرار التنقل في صف منفصل
    if navigation_buttons:
        nav_row = []
        for button in navigation_buttons:
            nav_row.append(InlineKeyboardButton(button['text'], callback_data=button['callback_data']))
        keyboard.append(nav_row)
    
    return InlineKeyboardMarkup(keyboard)

def create_pagination_keyboard(current_page, total_pages, prefix='page', add_back=True, add_cancel=True):
    """
    إنشاء لوحة مفاتيح للتنقل بين الصفحات
    
    Args:
        current_page: رقم الصفحة الحالية
        total_pages: إجمالي عدد الصفحات
        prefix: بادئة لبيانات الاستدعاء
        add_back: إضافة زر العودة
        add_cancel: إضافة زر الإلغاء
        
    Returns:
        InlineKeyboardMarkup: لوحة المفاتيح المنشأة
    """
    keyboard = []
    
    # أزرار التنقل بين الصفحات
    pagination_row = []
    
    # زر الصفحة السابقة
    if current_page > 1:
        pagination_row.append(InlineKeyboardButton('⬅️', callback_data=f'{prefix}:{current_page-1}'))
    
    # زر الصفحة الحالية
    pagination_row.append(InlineKeyboardButton(f'{current_page}/{total_pages}', callback_data=f'current_page'))
    
    # زر الصفحة التالية
    if current_page < total_pages:
        pagination_row.append(InlineKeyboardButton('➡️', callback_data=f'{prefix}:{current_page+1}'))
    
    keyboard.append(pagination_row)
    
    # أزرار التنقل الإضافية
    navigation_row = []
    
    if add_back:
        navigation_row.append(InlineKeyboardButton('🔙 رجوع', callback_data='back'))
    
    if add_cancel:
        navigation_row.append(InlineKeyboardButton('❌ إلغاء', callback_data='cancel'))
    
    if navigation_row:
        keyboard.append(navigation_row)
    
    return InlineKeyboardMarkup(keyboard)

def create_yes_no_keyboard(prefix='confirm', yes_text='✅ نعم', no_text='❌ لا'):
    """
    إنشاء لوحة مفاتيح نعم/لا بسيطة
    
    Args:
        prefix: بادئة لبيانات الاستدعاء
        yes_text: نص زر نعم
        no_text: نص زر لا
        
    Returns:
        InlineKeyboardMarkup: لوحة المفاتيح المنشأة
    """
    keyboard = [
        [
            InlineKeyboardButton(yes_text, callback_data=f'{prefix}:yes'),
            InlineKeyboardButton(no_text, callback_data=f'{prefix}:no')
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)
