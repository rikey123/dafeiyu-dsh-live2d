// Screen bytes enter the harness only through its native attachment admission.
// These attachments and the isolated agent's log follow DSH's retention policy;
// disposing an agent is not a promise that its durable history was erased.
export function screenImages(value, invalid) {
  if (!Array.isArray(value) || value.length !== 1) throw invalid();
  return value.map(image => {
    if (!image || image.mime_type !== 'image/jpeg' || !Number.isInteger(image.width) ||
        !Number.isInteger(image.height) || image.width < 1 || image.width > 960 ||
        image.height < 1 || image.height > 540 || typeof image.data !== 'string' ||
        image.data.length > 4 * Math.ceil(262144 / 3) ||
        !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(image.data)) throw invalid();
    const bytes = Buffer.from(image.data, 'base64');
    if (bytes.length < 4 || bytes.length > 262144 || bytes[0] !== 255 || bytes[1] !== 216 ||
        bytes.at(-2) !== 255 || bytes.at(-1) !== 217 || bytes.toString('base64') !== image.data) throw invalid();
    return { ...image };
  });
}

export async function admitScreen(ctx, images, selection, signal, unavailable) {
  const llm = typeof ctx.get === 'function' ? ctx.get('llm') : ctx.llm;
  const attachments = typeof ctx.get === 'function' ? ctx.get('attachments') : ctx.attachments;
  if (!llm?.resolveModelInfo || !attachments?.admitPromptContent) throw unavailable();
  const model = await llm.resolveModelInfo(selection.provider, selection.model, signal);
  // Unknown and text-only routes must never be called "screen understanding".
  if (!model?.inputModalities?.includes('image')) throw unavailable();
  signal.throwIfAborted();
  const parts = await attachments.admitPromptContent(images.map(image => ({
    type: 'image', mediaType: image.mime_type, data: image.data, name: 'shared-screen.jpg',
  })));
  signal.throwIfAborted();
  if (parts.length !== images.length || parts.some((part, i) => part.type !== 'image' ||
      part.attachment?.width !== images[i].width || part.attachment?.height !== images[i].height)) throw unavailable();
  return parts;
}
