package org.gk3hd.standalone;

import java.security.MessageDigest;
import java.util.Arrays;

/** Complete the pinned x86 Wine map result before its caller can reuse the stack. */
final class WineMapCompletion {
    static final int SIZE = 3194880;
    private static final String ORIGINAL =
        "5df5a68162694aac69256ad130c09a7caccba3fe7c6305e68db1844622c9d23b";
    private static final String COMPLETED =
        "b695f9cb731a14d748f748cf04442b1fb218dee622b95ff9ccdedcd99698052b";

    // Wine 10.10 from the pinned Winlator rootfs. Only verified zero .text
    // padding, its virtual extent and two instruction windows change. Relative
    // branches preserve relocation; the result is the actual worker HRESULT.
    // The source equivalent is preserved in wine-map-completion.patch.
    private static final Change[] CHANGES = {
        new Change(384, "508c1f00", "8d8c1f00"),
        new Change(1745942, "83ec248b7d08", "e935f8040090"),
        new Change(1746317, "8b45f085c0", "e9def60400"),
        new Change(2071632, "000000000000000000000000000000000000",
            "83ec248b7d08c745f0914a7ee1e9ba07fbff"),
        new Change(2071664, "0000000000000000000000000000000000000000000000000000000000",
            "5231c031d2f00fb155f05a3d914a7ee17504f390ebea85c0e90509fbff")
    };

    private WineMapCompletion() { }

    /** Return unchanged accepted output, or a verified private copy of the input. */
    static byte[] apply(byte[] input) throws Exception {
        if (input.length != SIZE)
            throw new IllegalStateException("The private Wine map runtime has an unexpected size");
        String identity = digest(input);
        if (COMPLETED.equals(identity)) return input;
        if (!ORIGINAL.equals(identity))
            throw new IllegalStateException("The private Wine map runtime is unsupported; existing data was preserved");
        byte[] output = input.clone();
        for (Change change : CHANGES) {
            if (!Arrays.equals(change.before,
                    Arrays.copyOfRange(input, change.offset, change.offset + change.before.length)))
                throw new IllegalStateException("The pinned Wine map instructions differ");
            System.arraycopy(change.after, 0, output, change.offset, change.after.length);
        }
        if (!COMPLETED.equals(digest(output)))
            throw new IllegalStateException("Wine map completion output verification failed");
        return output;
    }

    private static String digest(byte[] bytes) throws Exception {
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder text = new StringBuilder(64);
        for (byte value : hash) {
            text.append(Character.forDigit((value & 255) >>> 4, 16));
            text.append(Character.forDigit(value & 15, 16));
        }
        return text.toString();
    }

    private static byte[] decode(String text) {
        if (text.length() % 2 != 0) throw new IllegalArgumentException("Invalid map recipe");
        byte[] bytes = new byte[text.length() / 2];
        for (int i = 0; i < bytes.length; i++) {
            int high = Character.digit(text.charAt(i * 2), 16);
            int low = Character.digit(text.charAt(i * 2 + 1), 16);
            if (high < 0 || low < 0) throw new IllegalArgumentException("Invalid map recipe");
            bytes[i] = (byte)((high << 4) | low);
        }
        return bytes;
    }

    private static final class Change {
        final int offset;
        final byte[] before, after;
        Change(int offset, String before, String after) {
            this.offset = offset;
            this.before = decode(before);
            this.after = decode(after);
            if (this.before.length != this.after.length || offset < 0 ||
                    offset > SIZE - this.after.length)
                throw new IllegalArgumentException("Invalid map recipe bounds");
        }
    }
}
