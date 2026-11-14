package org.gk3hd.standalone;

import com.winlator.renderer.Texture;

/** Dirty upload flags are not evidence of a new GPU-backed window image. */
public final class TexturePublicationTests {
    private static void check(boolean okay,String text) {if(!okay) throw new AssertionError(text);}
    public static void run() {
        Texture texture=new Texture(null);
        long initial=texture.getContentGeneration();
        texture.setNeedsUpdate(true);
        long first=texture.getContentGeneration();
        check(first!=initial,"New publication retained the old generation");
        // GPU-backed windows have no CPU pixel buffer. Their upload flag stays
        // dirty even when updateFromDrawable has no work on repeated polls.
        for(int i=0;i<128;i++) {
            texture.updateFromDrawable();
            check(texture.isNeedsUpdate(),"Fixture no longer exercises persistent upload dirt");
            check(texture.getContentGeneration()==first,"Polling invented a new image");
        }
        texture.setNeedsUpdate(true);
        long second=texture.getContentGeneration();
        check(second!=first,"A second publication while dirty was lost");
        texture.setNeedsUpdate(false);
        check(texture.getContentGeneration()==second,"Upload acknowledgement invented a new image");
        check(new Texture(null).getContentGeneration()==initial,"Texture identity did not own its counter");
    }
}
