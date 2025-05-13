# إصلاح مشكلة التحقق من رمز تسجيل الدخول في Telegram API

## المشكلة

تم تحديد مشكلة في عملية التحقق من رمز تسجيل الدخول في خدمة المصادقة (auth_service.py). المشكلة الرئيسية كانت تتعلق بكيفية التعامل مع حالات انتهاء صلاحية الرمز وإعادة طلب رمز جديد.

من خلال تحليل سجلات الخطأ المقدمة، تبين أن المشكلة تحدث عندما ينتهي رمز التحقق ويحاول النظام طلب رمز جديد. في بعض الحالات، كان هذا يؤدي إلى خطأ "Phone code expired" وعدم القدرة على إكمال عملية تسجيل الدخول.

## الحل

تم إجراء التعديلات التالية لإصلاح المشكلة:

1. **إنشاء عميل جديد لطلب رمز جديد**: عند انتهاء صلاحية الرمز، يتم الآن إنشاء عميل Telegram جديد منفصل لطلب رمز جديد بدلاً من استخدام نفس العميل الذي فشل في التحقق من الرمز السابق. هذا يمنع تداخل الجلسات ويضمن عملية نظيفة لطلب رمز جديد.

2. **تحسين إدارة موارد العميل**: تم تحسين إدارة إنشاء وإغلاق عملاء Telegram لضمان إغلاق جميع الاتصالات بشكل صحيح، حتى في حالة حدوث أخطاء.

3. **إضافة خيار upsert للتأكد من إنشاء وثائق المستخدم**: تم إضافة خيار `upsert=True` عند تحديث بيانات المستخدم في قاعدة البيانات لضمان إنشاء وثيقة جديدة إذا لم تكن موجودة.

4. **تحسين التعامل مع الأخطاء**: تم إضافة فحوصات إضافية للتأكد من أن العملاء موجودون قبل محاولة إغلاقهم، مما يمنع الأخطاء المحتملة.

## التغييرات التفصيلية

### 1. إنشاء عميل جديد لطلب رمز جديد

```python
# إنشاء عميل جديد لطلب رمز جديد
new_client = None
try:
    if proxy:
        proxy_type, proxy_addr, proxy_port, proxy_username, proxy_password = self._parse_proxy(proxy)
        new_client = TelegramClient(
            StringSession(), 
            api_id, 
            api_hash,
            proxy=(proxy_type, proxy_addr, proxy_port, True, proxy_username, proxy_password)
        )
    else:
        new_client = TelegramClient(StringSession(), api_id, api_hash)
    
    await new_client.connect()
    result = await new_client.send_code_request(phone_number)
    new_phone_code_hash = result.phone_code_hash
    
    # إغلاق العميل الجديد
    await new_client.disconnect()
    
    return (False, f"❌ انتهت صلاحية رمز التحقق.\n\nتم إرسال رمز جديد إلى هاتفك. يرجى إدخال الرمز الجديد.", None, new_phone_code_hash)
except Exception as e:
    if new_client:
        await new_client.disconnect()
    raise e
```

### 2. تحسين إدارة موارد العميل

```python
client = None
try:
    # إنشاء العميل وتنفيذ العمليات
    # ...
except Exception as e:
    # معالجة الخطأ
    # ...
finally:
    # دائماً قم بإغلاق العميل
    if client:
        try:
            await client.disconnect()
        except:
            pass
```

### 3. إضافة خيار upsert للتأكد من إنشاء وثائق المستخدم

```python
# حفظ phone_code_hash في قاعدة البيانات لهذا المستخدم
self.users_collection.update_one(
    {'user_id': user_id},
    {'$set': {
        'phone_code_hash': phone_code_hash,
        'api_id': api_id,
        'api_hash': api_hash,
        'phone_number': phone_number,
        'code_request_time': datetime.now(),
        'code_resend_attempts': 0,
        'code_input_attempts': 0,
        'updated_at': datetime.now()
    }},
    upsert=True  # إنشاء وثيقة جديدة إذا لم تكن موجودة
)
```

## كيفية الاختبار

تم اختبار الحل من خلال محاكاة سيناريو انتهاء صلاحية الرمز والتأكد من أن النظام يتعامل معه بشكل صحيح. الإصلاح يضمن أن:

1. عند انتهاء صلاحية الرمز، يتم إنشاء عميل جديد لطلب رمز جديد.
2. يتم إغلاق جميع الاتصالات بشكل صحيح لتجنب تسرب الموارد.
3. يتم تخزين بيانات المستخدم بشكل صحيح في قاعدة البيانات.

## ملاحظات إضافية

هذا الإصلاح يحسن بشكل كبير موثوقية عملية المصادقة، خاصة في الحالات التي ينتهي فيها رمز التحقق. يجب أن يعمل النظام الآن بشكل أكثر استقراراً ويتعامل بشكل أفضل مع حالات الخطأ المختلفة.
