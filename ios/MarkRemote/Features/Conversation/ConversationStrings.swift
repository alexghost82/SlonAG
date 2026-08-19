import Foundation

/// Russian user-visible copy for Conversation.
public enum ConversationStrings: Sendable {
    public static let title = "Чат"
    public static let emptyTitle = "Нет сообщений"
    public static let emptyMessage = "Напишите сообщение или удерживайте кнопку микрофона."
    public static let inputPlaceholder = "Сообщение…"
    public static let send = "Отправить"
    public static let cancel = "Отменить"
    public static let cancelGeneration = "Остановить генерацию"
    public static let attach = "Вложение"
    public static let camera = "Камера"
    public static let attachStubHint = "Загрузка файлов пока недоступна"
    public static let cameraStubHint = "Камера пока недоступна"
    public static let pendingApprovals = "Ожидают подтверждения"
    public static let approvalChipFallback = "Действие"
    public static let streaming = "Печатает…"
    public static let errorGeneric = "Не удалось отправить сообщение"
    public static let roleUser = "Вы"
    public static let roleAssistant = "Ассистент"
    /// Explicit product guarantee: device never holds provider keys.
    public static let noProviderKeysOnDevice = "Ключи AI-провайдеров на устройстве не хранятся"
}
