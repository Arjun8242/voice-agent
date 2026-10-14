export function extractNextSentence(buffer: string) {
    const index = buffer.search(/[.!?]/);
    if (index === -1) return null;
    return {
        sentence: buffer.slice(0, index + 1).trim(),
        remaining: buffer.slice(index + 1).trim(),
    };
}

//Hello there. How are you?
// sentence:"Hello there."
// remaining: "How are you?"

export function extractSentences(buffer: string) {
    const sentences: string[] = [];
    let remaining = buffer;

    while (true) {
        const result = extractNextSentence(remaining);
        if (!result) break;
        sentences.push(result.sentence);
        remaining = result.remaining;
    }

    //filter out empty whitespace sentences
    return { sentences: sentences.filter((s) => s.length > 0), remaining };
}