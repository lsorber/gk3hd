package org.gk3hd.standalone;

/** Fixed US physical strokes for the bounded ASCII developer-console fixture. */
public final class NativeConsoleKeys {
    private NativeConsoleKeys() {}
    public static String key(char value) {
        if(value>='a'&&value<='z')return "KEY_"+Character.toUpperCase(value);
        if((value>='A'&&value<='Z')||(value>='0'&&value<='9'))return "KEY_"+value;
        switch(value) {
            case '"':return "KEY_APOSTROPHE";
            case '(':return "KEY_9";
            case ')':return "KEY_0";
            case ',':return "KEY_COMMA";
            case '.':return "KEY_PERIOD";
            case '-':return "KEY_MINUS";
            case '_':return "KEY_MINUS";
            case ';':return "KEY_SEMICOLON";
            default:throw new IllegalArgumentException("Unsupported console fixture character");
        }
    }
    public static boolean shift(char value) {
        key(value);
        return (value>='A'&&value<='Z')||value=='"'||value=='('||value==')'||value=='_';
    }
}
