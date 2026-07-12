from patcher import Patcher

p = Patcher()

#r = p.list_patches(apk_path="/home/oguz/re1sid/.revanced_res/youtube.apk")
#with open("output.txt", "w") as f:
#    for i in r:
#        f.write(str(i) + "\n")

for line in p.patch_apk(apk_path="/home/oguz/re1sid/.revanced_res/youtube.apk", 
                          output_path="/home/oguz/re1sid/.revanced_res/youtube_patched.apk", 
                          enabled_patches=[284], 
                          disabled_patches=None, 
                          options={"remove_ads": True}, 
                          exclusive=True, force=False, 
                          bypass_verification=True, 
                          stream_output=True):
    print(line)